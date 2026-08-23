from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from app.application.ports import (
    CorpusArchiveReaderPort,
    CorpusRepositoryPort,
    EmbeddingPort,
    PublicRetrievalCachePort,
    VersionedCorpusIndexPort,
)
from app.application.rag_dtos import (
    CorpusArchiveData,
    CorpusDatasetSpec,
    CorpusImportResult,
)


_T = TypeVar("_T")
_SAFE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")
_SAFE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def versioned_collection_names(
    prefix: str,
    version: str,
    archive_sha256: str,
) -> tuple[str, str]:
    if not _SAFE_NAME_RE.fullmatch(prefix):
        raise ValueError("Milvus collection prefix is invalid")
    if not _SAFE_VERSION_RE.fullmatch(version):
        raise ValueError("RAG dataset version is invalid")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", archive_sha256):
        raise ValueError("RAG archive SHA-256 is invalid")
    safe_version = re.sub(r"[^A-Za-z0-9_]", "_", version)
    collection = f"{prefix}_{safe_version}_{archive_sha256[:8].lower()}"
    return collection, f"{collection}_route"


class RagCorpusImportCoordinator:
    """Resumable, idempotent import of a sanitized group RAG archive."""

    def __init__(
        self,
        archive_reader: CorpusArchiveReaderPort,
        repository: CorpusRepositoryPort,
        embedding: EmbeddingPort,
        index: VersionedCorpusIndexPort,
        *,
        cache: PublicRetrievalCachePort | None = None,
        batch_size: int = 500,
        batch_retries: int = 2,
    ) -> None:
        if batch_size < 1 or batch_size > 1000:
            raise ValueError("RAG import batch size is out of range")
        if batch_retries < 0 or batch_retries > 5:
            raise ValueError("RAG import retries are out of range")
        self.archive_reader = archive_reader
        self.repository = repository
        self.embedding = embedding
        self.index = index
        self.cache = cache
        self.batch_size = batch_size
        self.batch_retries = batch_retries

    def inspect(
        self,
        archive_path: str,
        *,
        expected_sha256: str | None,
        expected_chunk_count: int = 15_858,
    ) -> CorpusArchiveData:
        return self.archive_reader.read(
            archive_path,
            expected_sha256=expected_sha256,
            expected_chunk_count=expected_chunk_count,
        )

    async def run(
        self,
        archive: CorpusArchiveData,
        spec: CorpusDatasetSpec,
    ) -> CorpusImportResult:
        if archive.archive_sha256.lower() != spec.archive_sha256.lower():
            raise ValueError("dataset spec does not match archive SHA-256")
        if len(archive.chunks) != spec.expected_chunk_count:
            raise ValueError("dataset spec does not match archive chunk count")
        if spec.embedding_model != self.embedding.model_name:
            raise ValueError("dataset embedding model does not match adapter")
        if spec.embedding_dimension != self.embedding.dimension:
            raise ValueError("dataset embedding dimension does not match adapter")

        state = await self.repository.ensure_dataset(spec, archive)
        created_embeddings = reused_embeddings = 0
        try:
            await self._retry(lambda: self.index.ensure_collections(spec))
            while True:
                chunks = await self.repository.pending_chunks(
                    state.dataset_id, self.batch_size
                )
                if not chunks:
                    break
                text_by_hash = {
                    item.content_hash: item.content for item in chunks
                }
                vectors_by_hash, created, reused = await self._embeddings(text_by_hash)
                created_embeddings += created
                reused_embeddings += reused
                vectors = [vectors_by_hash[item.content_hash] for item in chunks]
                await self._retry(
                    lambda: self.index.upsert_chunks(spec, chunks, vectors)
                )
                await self.repository.mark_chunks_indexed(
                    state.dataset_id, [item.external_id for item in chunks]
                )

            # Route writes are idempotent by primary key, but Milvus' physical
            # row_count includes upsert tombstones until compaction. Skip a
            # complete route set and use logical count(*) for all gates.
            existing_routes = await self._retry(
                lambda: self.index.count_routes(spec)
            )
            if existing_routes != len(archive.routes):
                for start in range(0, len(archive.routes), self.batch_size):
                    routes = archive.routes[start:start + self.batch_size]
                    text_by_hash = {
                        item.content_hash: item.document_title for item in routes
                    }
                    vectors_by_hash, created, reused = await self._embeddings(
                        text_by_hash
                    )
                    created_embeddings += created
                    reused_embeddings += reused
                    vectors = [vectors_by_hash[item.content_hash] for item in routes]
                    await self._retry(
                        lambda routes=routes, vectors=vectors: self.index.upsert_routes(
                            spec, routes, vectors
                        )
                    )

            indexed = await self._retry(lambda: self.index.count_chunks(spec))
            if indexed != spec.expected_chunk_count:
                raise RuntimeError(
                    "Milvus corpus row count does not match the sanitized manifest"
                )
            indexed_routes = await self._retry(
                lambda: self.index.count_routes(spec)
            )
            if indexed_routes != len(archive.routes):
                raise RuntimeError(
                    "Milvus route row count does not match the sanitized manifest"
                )
            await self._retry(lambda: self.index.activate_aliases(spec))
            await self.repository.mark_dataset_active(state.dataset_id, indexed)
            if self.cache is not None:
                try:
                    await self.cache.invalidate_public()
                except Exception:
                    # Cache v3 includes the dataset version, so failed eager
                    # invalidation cannot expose results from another version.
                    pass
        except Exception as exc:
            await self.repository.mark_dataset_failed(
                state.dataset_id, type(exc).__name__
            )
            raise

        warnings = ["组员RAG语料仅作为演示参考，内容时效仍需核验。"]
        if spec.license_status != "APPROVED":
            warnings.append("组员RAG语料的上云授权尚未标记为已批准。")
        if archive.sanitized_phone_count or archive.sanitized_email_count:
            warnings.append("导入前已脱敏语料中的手机号和邮箱。")
        return CorpusImportResult(
            dataset_id=state.dataset_id,
            dataset_version=spec.version,
            status="ACTIVE",
            chunks=spec.expected_chunk_count,
            routes=len(archive.routes),
            unique_embeddings=created_embeddings,
            reused_embeddings=reused_embeddings,
            collection_name=spec.collection_name,
            route_collection_name=spec.route_collection_name,
            warnings=warnings,
        )

    async def _embeddings(
        self, text_by_hash: dict[str, str]
    ) -> tuple[dict[str, list[float]], int, int]:
        hashes = list(text_by_hash)
        cached = await self.repository.cached_embeddings(
            hashes, self.embedding.model_name, self.embedding.dimension
        )
        missing_hashes = [item for item in hashes if item not in cached]
        created: dict[str, list[float]] = {}
        # The provider adapter enforces its own remote batch limit and bounded
        # retries. Keeping this group small also bounds checkpoint loss.
        for start in range(0, len(missing_hashes), 100):
            part_hashes = missing_hashes[start:start + 100]
            texts = [text_by_hash[item] for item in part_hashes]
            vectors = await self.embedding.embed_texts(texts)
            if len(vectors) != len(part_hashes):
                raise RuntimeError("embedding result count does not match request")
            created.update(zip(part_hashes, vectors, strict=True))
            await self.repository.store_embeddings(
                dict(zip(part_hashes, vectors, strict=True)),
                self.embedding.model_name,
                self.embedding.dimension,
            )
        return {**cached, **created}, len(created), len(cached)

    async def _retry(self, operation: Callable[[], Awaitable[_T]]) -> _T:
        last_error: BaseException | None = None
        for attempt in range(self.batch_retries + 1):
            try:
                return await operation()
            except Exception as exc:
                last_error = exc
                if attempt >= self.batch_retries:
                    break
                await asyncio.sleep(min(0.25 * (2**attempt), 2.0))
        assert last_error is not None
        raise last_error
