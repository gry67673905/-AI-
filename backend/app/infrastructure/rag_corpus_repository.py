from __future__ import annotations

import math
import struct
from collections.abc import Iterable
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.application.rag_dtos import (
    CorpusArchiveData,
    CorpusChunkData,
    CorpusDatasetSpec,
    CorpusDatasetState,
)
from app.infrastructure.records import (
    KnowledgeCorpusChunkRecord,
    KnowledgeDatasetRecord,
    KnowledgeEmbeddingCacheRecord,
)


def _batches(values: list[Any], size: int) -> Iterable[list[Any]]:
    for start in range(0, len(values), size):
        yield values[start:start + size]


class SqlAlchemyCorpusRepository:
    """PostgreSQL checkpoint store for resumable corpus imports."""

    insert_batch_size = 500

    def __init__(self, sessions: Any) -> None:
        self.sessions = sessions

    @staticmethod
    def dataset_id(spec: CorpusDatasetSpec) -> UUID:
        return uuid5(
            NAMESPACE_URL,
            f"smart-gov-rag:{spec.name}:{spec.version}:{spec.archive_sha256}",
        )

    async def ensure_dataset(
        self, spec: CorpusDatasetSpec, archive: CorpusArchiveData
    ) -> CorpusDatasetState:
        dataset_id = self.dataset_id(spec)
        async with self.sessions() as session, session.begin():
            existing = await session.scalar(
                select(KnowledgeDatasetRecord)
                .where(
                    KnowledgeDatasetRecord.name == spec.name,
                    KnowledgeDatasetRecord.version == spec.version,
                )
                .with_for_update()
            )
            reused = existing is not None
            if existing is not None:
                self._require_same_dataset(existing, spec)
                record = existing
            else:
                record = KnowledgeDatasetRecord(
                    id=dataset_id,
                    name=spec.name,
                    version=spec.version,
                    archive_sha256=spec.archive_sha256,
                    manifest_hash=spec.manifest_hash,
                    source_owner=spec.source_owner,
                    license_status=spec.license_status,
                    status="INDEXING",
                    expected_chunk_count=spec.expected_chunk_count,
                    imported_chunk_count=0,
                    indexed_chunk_count=0,
                    embedding_model=spec.embedding_model,
                    embedding_dimension=spec.embedding_dimension,
                    collection_name=spec.collection_name,
                    route_collection_name=spec.route_collection_name,
                    collection_alias=spec.collection_alias,
                    route_alias=spec.route_alias,
                    attempts=0,
                    manifest_json={},
                )
                session.add(record)
                await session.flush()

            if record.status != "ACTIVE":
                record.status = "INDEXING"
                record.attempts += 1
                record.last_error = None
            record.manifest_json = {
                "archive_sha256": spec.archive_sha256,
                "manifest_hash": spec.manifest_hash,
                "topics": archive.topics,
                "routes": len(archive.routes),
                "sanitized_phone_count": archive.sanitized_phone_count,
                "sanitized_email_count": archive.sanitized_email_count,
                "demo_data": True,
                "license_authorized": spec.license_status == "APPROVED",
                "content_currency_verified": False,
            }

            rows = [
                {
                    "id": uuid5(dataset_id, f"{item.topic_slug}:{item.external_id}"),
                    "dataset_id": dataset_id,
                    "external_id": item.external_id,
                    "topic_slug": item.topic_slug,
                    "topic_name": item.topic_name,
                    "document_title": item.document_title,
                    "section": item.section,
                    "chunk_type": item.chunk_type,
                    "theme": item.theme,
                    "content": item.content,
                    "source_content_hash": item.source_content_hash,
                    "content_hash": item.content_hash,
                    "status": "PENDING",
                    # ORM bulk inserts use the mapped attribute key, not the
                    # underlying SQL column name (which is ``metadata``).
                    # Using ``metadata`` here collides with DeclarativeBase's
                    # class-level metadata object before any row is written.
                    "metadata_json": {
                        "demo_data": True,
                        "license_authorized": spec.license_status == "APPROVED",
                        "content_currency_verified": False,
                    },
                }
                for item in archive.chunks
            ]
            for batch in _batches(rows, self.insert_batch_size):
                statement = pg_insert(KnowledgeCorpusChunkRecord).values(batch)
                await session.execute(
                    statement.on_conflict_do_nothing(
                        constraint="uq_corpus_chunk_dataset_external"
                    )
                )
            imported = int(
                await session.scalar(
                    select(func.count())
                    .select_from(KnowledgeCorpusChunkRecord)
                    .where(KnowledgeCorpusChunkRecord.dataset_id == dataset_id)
                )
                or 0
            )
            if imported != spec.expected_chunk_count:
                raise ValueError("persisted corpus chunk count does not match manifest")
            record.imported_chunk_count = imported
            indexed = int(
                await session.scalar(
                    select(func.count())
                    .select_from(KnowledgeCorpusChunkRecord)
                    .where(
                        KnowledgeCorpusChunkRecord.dataset_id == dataset_id,
                        KnowledgeCorpusChunkRecord.status.in_(["INDEXED", "ACTIVE"]),
                    )
                )
                or 0
            )
            record.indexed_chunk_count = indexed
            return CorpusDatasetState(
                dataset_id=dataset_id,
                status=record.status,
                expected_chunk_count=record.expected_chunk_count,
                indexed_chunk_count=indexed,
                reused=reused,
            )

    @staticmethod
    def _require_same_dataset(
        record: KnowledgeDatasetRecord, spec: CorpusDatasetSpec
    ) -> None:
        expected = (
            spec.archive_sha256,
            spec.manifest_hash,
            spec.expected_chunk_count,
            spec.embedding_model,
            spec.embedding_dimension,
            spec.collection_name,
            spec.route_collection_name,
        )
        actual = (
            record.archive_sha256,
            record.manifest_hash,
            record.expected_chunk_count,
            record.embedding_model,
            record.embedding_dimension,
            record.collection_name,
            record.route_collection_name,
        )
        if actual != expected:
            raise ValueError("dataset version already exists with a different manifest")

    async def pending_chunks(
        self, dataset_id: UUID, limit: int
    ) -> list[CorpusChunkData]:
        async with self.sessions() as session:
            rows = list(
                (
                    await session.scalars(
                        select(KnowledgeCorpusChunkRecord)
                        .where(
                            KnowledgeCorpusChunkRecord.dataset_id == dataset_id,
                            KnowledgeCorpusChunkRecord.status.in_([
                                "PENDING", "INDEX_FAILED"
                            ]),
                        )
                        .order_by(KnowledgeCorpusChunkRecord.external_id)
                        .limit(limit)
                    )
                ).all()
            )
        return [
            CorpusChunkData(
                external_id=item.external_id,
                topic_slug=item.topic_slug,
                topic_name=item.topic_name,
                document_title=item.document_title,
                section=item.section,
                chunk_type=item.chunk_type,
                content=item.content,
                source_content_hash=item.source_content_hash,
                content_hash=item.content_hash,
                theme=item.theme,
            )
            for item in rows
        ]

    async def cached_embeddings(
        self, content_hashes: list[str], model: str, dimension: int
    ) -> dict[str, list[float]]:
        if not content_hashes:
            return {}
        result: dict[str, list[float]] = {}
        unique_hashes = list(dict.fromkeys(content_hashes))
        async with self.sessions() as session:
            for batch in _batches(unique_hashes, 500):
                rows = (
                    await session.scalars(
                        select(KnowledgeEmbeddingCacheRecord).where(
                            KnowledgeEmbeddingCacheRecord.content_hash.in_(batch),
                            KnowledgeEmbeddingCacheRecord.model == model,
                            KnowledgeEmbeddingCacheRecord.dimension == dimension,
                        )
                    )
                ).all()
                for row in rows:
                    expected_bytes = dimension * 4
                    if len(row.vector_bytes) != expected_bytes:
                        continue
                    result[row.content_hash] = list(
                        struct.unpack(f"<{dimension}f", row.vector_bytes)
                    )
        return result

    async def store_embeddings(
        self,
        embeddings: dict[str, list[float]],
        model: str,
        dimension: int,
    ) -> None:
        if not embeddings:
            return
        rows: list[dict[str, Any]] = []
        for content_hash, vector in embeddings.items():
            if len(vector) != dimension or not all(math.isfinite(item) for item in vector):
                raise ValueError("embedding cache vector is invalid")
            rows.append(
                {
                    "content_hash": content_hash,
                    "model": model,
                    "dimension": dimension,
                    "vector_bytes": struct.pack(f"<{dimension}f", *vector),
                }
            )
        async with self.sessions() as session, session.begin():
            for batch in _batches(rows, self.insert_batch_size):
                statement = pg_insert(KnowledgeEmbeddingCacheRecord).values(batch)
                await session.execute(
                    statement.on_conflict_do_nothing(
                        constraint="uq_knowledge_embedding_content_model_dimension"
                    )
                )

    async def mark_chunks_indexed(
        self, dataset_id: UUID, external_ids: list[str]
    ) -> None:
        if not external_ids:
            return
        async with self.sessions() as session, session.begin():
            await session.execute(
                update(KnowledgeCorpusChunkRecord)
                .where(
                    KnowledgeCorpusChunkRecord.dataset_id == dataset_id,
                    KnowledgeCorpusChunkRecord.external_id.in_(external_ids),
                )
                .values(status="INDEXED", indexed_at=func.now())
            )
            indexed = int(
                await session.scalar(
                    select(func.count())
                    .select_from(KnowledgeCorpusChunkRecord)
                    .where(
                        KnowledgeCorpusChunkRecord.dataset_id == dataset_id,
                        KnowledgeCorpusChunkRecord.status.in_(["INDEXED", "ACTIVE"]),
                    )
                )
                or 0
            )
            await session.execute(
                update(KnowledgeDatasetRecord)
                .where(KnowledgeDatasetRecord.id == dataset_id)
                .values(indexed_chunk_count=indexed)
            )

    async def mark_dataset_active(
        self, dataset_id: UUID, indexed_chunk_count: int
    ) -> None:
        async with self.sessions() as session, session.begin():
            await session.execute(
                update(KnowledgeCorpusChunkRecord)
                .where(KnowledgeCorpusChunkRecord.dataset_id == dataset_id)
                .values(status="ACTIVE")
            )
            await session.execute(
                update(KnowledgeDatasetRecord)
                .where(KnowledgeDatasetRecord.id == dataset_id)
                .values(
                    status="ACTIVE",
                    indexed_chunk_count=indexed_chunk_count,
                    last_error=None,
                )
            )

    async def mark_dataset_failed(
        self, dataset_id: UUID, error_code: str
    ) -> None:
        safe_code = error_code[:100] if error_code else "UnknownError"
        async with self.sessions() as session, session.begin():
            await session.execute(
                update(KnowledgeDatasetRecord)
                .where(KnowledgeDatasetRecord.id == dataset_id)
                .values(status="INDEX_FAILED", last_error=safe_code)
            )
