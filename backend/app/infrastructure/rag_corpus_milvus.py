from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from app.application.dtos import SourceData
from app.application.ports import EmbeddingPort
from app.application.rag_dtos import (
    CorpusChunkData,
    CorpusDatasetSpec,
    CorpusRouteData,
)


def _milvus_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:48]}"


class VersionedMilvusCorpusIndex:
    """Versioned 1024-dimensional corpus collections with active aliases."""

    def __init__(
        self,
        uri: str,
        timeout_seconds: float,
        dimension: int,
        *,
        client: Any | None = None,
    ) -> None:
        self.uri = uri
        self.timeout_seconds = timeout_seconds
        self.dimension = dimension
        self._client = client
        self._client_lock = asyncio.Lock()
        self._collection_lock = asyncio.Lock()

    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is None:
                from pymilvus import MilvusClient

                async with asyncio.timeout(self.timeout_seconds):
                    self._client = await asyncio.to_thread(
                        MilvusClient,
                        uri=self.uri,
                        timeout=self.timeout_seconds,
                    )
        return self._client

    async def ensure_collections(self, spec: CorpusDatasetSpec) -> None:
        if spec.embedding_dimension != self.dimension:
            raise ValueError("corpus collection dimension does not match embedding port")
        client = await self._get_client()

        def ensure() -> None:
            for name in (spec.collection_name, spec.route_collection_name):
                if client.has_collection(collection_name=name):
                    continue
                try:
                    client.create_collection(
                        collection_name=name,
                        dimension=self.dimension,
                        primary_field_name="id",
                        id_type="string",
                        vector_field_name="vector",
                        metric_type="COSINE",
                        auto_id=False,
                        max_length=64,
                        consistency_level="Strong",
                    )
                except Exception as create_error:
                    try:
                        created_elsewhere = client.has_collection(
                            collection_name=name
                        )
                    except Exception:
                        raise create_error
                    if not created_elsewhere:
                        raise

        async with self._collection_lock:
            async with asyncio.timeout(self.timeout_seconds * 2):
                await asyncio.to_thread(ensure)

    async def upsert_chunks(
        self,
        spec: CorpusDatasetSpec,
        chunks: list[CorpusChunkData],
        vectors: list[list[float]],
    ) -> None:
        self._validate_vectors(vectors, len(chunks))
        if not chunks:
            return
        client = await self._get_client()
        rows = [
            {
                "id": _milvus_id(
                    "rc", spec.archive_sha256, item.topic_slug, item.external_id
                ),
                "vector": vector,
                "dataset_version": spec.version,
                "external_id": item.external_id,
                "topic_slug": item.topic_slug,
                "topic_name": item.topic_name,
                "doc_title": item.document_title,
                "section": item.section,
                "chunk_type": item.chunk_type,
                "theme": item.theme or "",
                "content": item.content,
                "content_hash": item.content_hash,
                "status": "ACTIVE",
                "demo_data": True,
                "license_authorized": spec.license_status == "APPROVED",
                "content_currency_verified": False,
            }
            for item, vector in zip(chunks, vectors, strict=True)
        ]
        async with asyncio.timeout(self.timeout_seconds * 3):
            await asyncio.to_thread(
                client.upsert, collection_name=spec.collection_name, data=rows
            )

    async def upsert_routes(
        self,
        spec: CorpusDatasetSpec,
        routes: list[CorpusRouteData],
        vectors: list[list[float]],
    ) -> None:
        self._validate_vectors(vectors, len(routes))
        if not routes:
            return
        client = await self._get_client()
        rows = [
            {
                "id": _milvus_id(
                    "rr", spec.archive_sha256, item.topic_slug,
                    item.document_title,
                ),
                "vector": vector,
                "dataset_version": spec.version,
                "topic_slug": item.topic_slug,
                "topic_name": item.topic_name,
                "doc_title": item.document_title,
                "status": "ACTIVE",
            }
            for item, vector in zip(routes, vectors, strict=True)
        ]
        async with asyncio.timeout(self.timeout_seconds * 3):
            await asyncio.to_thread(
                client.upsert,
                collection_name=spec.route_collection_name,
                data=rows,
            )

    async def count_chunks(self, spec: CorpusDatasetSpec) -> int:
        client = await self._get_client()

        def count() -> int:
            client.flush(collection_name=spec.collection_name)
            return self._logical_count(
                client, spec.collection_name, spec.version
            )

        async with asyncio.timeout(self.timeout_seconds * 3):
            return await asyncio.to_thread(count)

    async def count_routes(self, spec: CorpusDatasetSpec) -> int:
        """Flush and count route vectors before either active alias can move."""

        client = await self._get_client()

        def count() -> int:
            client.flush(collection_name=spec.route_collection_name)
            return self._logical_count(
                client, spec.route_collection_name, spec.version
            )

        async with asyncio.timeout(self.timeout_seconds * 3):
            return await asyncio.to_thread(count)

    @staticmethod
    def _logical_count(
        client: Any, collection_name: str, version: str | None = None
    ) -> int:
        """Count live primary keys, excluding physical upsert tombstones."""

        filters = ['status == "ACTIVE"']
        if version is not None:
            encoded_version = json.dumps(version, ensure_ascii=False)
            filters.insert(0, f"dataset_version == {encoded_version}")
        rows = client.query(
            collection_name=collection_name,
            filter=" && ".join(filters),
            output_fields=["count(*)"],
            consistency_level="Strong",
        )
        if not rows or not isinstance(rows[0], dict):
            raise RuntimeError("Milvus logical row count is unavailable")
        value = rows[0].get("count(*)")
        if value is None:
            raise RuntimeError("Milvus logical row count is unavailable")
        return int(value)

    async def activate_aliases(self, spec: CorpusDatasetSpec) -> None:
        client = await self._get_client()

        def activate_one(collection: str, alias: str) -> None:
            try:
                client.describe_alias(alias=alias)
            except Exception:
                try:
                    client.create_alias(collection_name=collection, alias=alias)
                    return
                except Exception:
                    # A concurrent importer may have created the alias.
                    pass
            client.alter_alias(collection_name=collection, alias=alias)

        def activate() -> None:
            # Switching is idempotent. If the process stops between the two
            # aliases, a retry converges both aliases to the same dataset version.
            activate_one(spec.collection_name, spec.collection_alias)
            activate_one(spec.route_collection_name, spec.route_alias)

        async with asyncio.timeout(self.timeout_seconds * 2):
            await asyncio.to_thread(activate)

    async def ping_active(
        self,
        *,
        collection_alias: str,
        route_alias: str,
        expected_collection: str,
        expected_route_collection: str,
        expected_chunk_count: int,
        expected_route_count: int,
    ) -> None:
        """Validate active aliases and row counts without a paid embedding call."""

        client = await self._get_client()

        def target(description: Any) -> str:
            if not isinstance(description, dict):
                return ""
            return str(
                description.get("collection_name")
                or description.get("collection")
                or ""
            )

        def check() -> None:
            collection_target = target(client.describe_alias(alias=collection_alias))
            route_target = target(client.describe_alias(alias=route_alias))
            if collection_target != expected_collection:
                raise RuntimeError("group corpus alias points to another dataset version")
            if route_target != expected_route_collection:
                raise RuntimeError("group route alias points to another dataset version")
            if not client.has_collection(collection_name=collection_target):
                raise RuntimeError("group corpus collection is missing")
            if not client.has_collection(collection_name=route_target):
                raise RuntimeError("group route collection is missing")
            # The aliases have already been proven to target the exact
            # versioned collection names, so a live-primary-key count is
            # sufficient and does not depend on parsing names back to versions.
            chunk_count = self._logical_count(client, collection_target)
            route_count = self._logical_count(client, route_target)
            if chunk_count != expected_chunk_count:
                raise RuntimeError("group corpus row count is invalid")
            if route_count != expected_route_count:
                raise RuntimeError("group route row count is invalid")

        async with asyncio.timeout(self.timeout_seconds * 2):
            await asyncio.to_thread(check)

    def _validate_vectors(self, vectors: list[list[float]], expected: int) -> None:
        if len(vectors) != expected or any(
            len(vector) != self.dimension for vector in vectors
        ):
            raise ValueError("corpus vector count or dimension is invalid")


class GroupCorpusRetriever:
    """Query the active group corpus through its route and content aliases."""

    def __init__(
        self,
        index: VersionedMilvusCorpusIndex,
        embedding: EmbeddingPort,
        *,
        dataset_version: str,
        collection_alias: str,
        route_alias: str,
    ) -> None:
        self.index = index
        self.embedding = embedding
        self.dataset_version = dataset_version
        self.collection_alias = collection_alias
        self.route_alias = route_alias

    async def search(self, query: str, limit: int = 6) -> list[SourceData]:
        vectors = await self.embedding.embed_texts([query])
        if len(vectors) != 1:
            raise RuntimeError("group corpus query embedding is unavailable")
        client = await self.index._get_client()
        vector = vectors[0]

        def perform() -> list[SourceData]:
            version = json.dumps(self.dataset_version, ensure_ascii=False)
            route_rows = client.search(
                collection_name=self.route_alias,
                data=[vector],
                limit=24,
                output_fields=["topic_slug", "topic_name", "doc_title"],
                filter=f'dataset_version == {version} && status == "ACTIVE"',
                search_params={"metric_type": "COSINE", "params": {}},
            )
            topics: list[str] = []
            for hit in route_rows[0] if route_rows else []:
                entity = hit.get("entity", hit)
                slug = str(entity.get("topic_slug", ""))
                if slug and slug not in topics:
                    topics.append(slug)
                if len(topics) == 3:
                    break
            filters = [f'dataset_version == {version}', 'status == "ACTIVE"']
            if topics:
                filters.append(
                    "topic_slug in [" + ",".join(json.dumps(item) for item in topics) + "]"
                )
            rows = client.search(
                collection_name=self.collection_alias,
                data=[vector],
                limit=max(limit * 3, 18),
                output_fields=[
                    "external_id", "topic_slug", "topic_name", "doc_title",
                    "section", "chunk_type", "content", "content_hash",
                ],
                filter=" && ".join(filters),
                search_params={"metric_type": "COSINE", "params": {}},
            )
            sources: list[SourceData] = []
            seen_documents: set[tuple[str, str]] = set()
            for hit in rows[0] if rows else []:
                entity = hit.get("entity", hit)
                topic_slug = str(entity.get("topic_slug", ""))
                title = str(entity.get("doc_title", "")).strip()
                external_id = str(entity.get("external_id", "")).strip()
                content = str(entity.get("content", "")).strip()
                if not topic_slug or not title or not external_id or not content:
                    continue
                document_key = (topic_slug, title)
                if document_key in seen_documents:
                    continue
                seen_documents.add(document_key)
                score = hit.get("distance") if isinstance(hit, dict) else None
                sources.append(
                    SourceData(
                        kind="rag",
                        title=f"{title}（组员RAG·未核验演示参考）",
                        reference=(
                            f"ragdb://{self.dataset_version}/{topic_slug}/"
                            f"{external_id}"
                        ),
                        excerpt=content[:600],
                        score=float(score) if score is not None else None,
                    )
                )
                if len(sources) >= limit:
                    break
            return sources

        async with asyncio.timeout(self.index.timeout_seconds * 2):
            return await asyncio.to_thread(perform)
