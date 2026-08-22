from __future__ import annotations

import asyncio
from typing import Any

from app.knowledge import EMBEDDING_DIMENSION, hash_embedding
from app.application.dtos import SourceData


class MilvusRAG:
    def __init__(self, uri: str, collection: str, timeout_seconds: float):
        self.uri = uri
        self.collection = collection
        self.timeout_seconds = timeout_seconds
        self._client: Any = None
        self._client_lock = asyncio.Lock()
        self._collection_init_lock = asyncio.Lock()

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

    async def ping(self) -> None:
        client = await self._get_client()
        async with asyncio.timeout(self.timeout_seconds):
            await asyncio.to_thread(client.list_collections)

    async def _ensure_collection(self, client: Any) -> None:
        def create_if_missing() -> None:
            if client.has_collection(collection_name=self.collection):
                return
            try:
                client.create_collection(
                    collection_name=self.collection,
                    dimension=EMBEDDING_DIMENSION,
                    primary_field_name="id",
                    id_type="string",
                    vector_field_name="vector",
                    metric_type="COSINE",
                    auto_id=False,
                    max_length=64,
                    consistency_level="Strong",
                )
            except Exception as create_error:
                # Another API replica may have created the collection between
                # has_collection and create_collection. Only suppress the
                # create error after Milvus confirms that the target now exists.
                try:
                    created_elsewhere = client.has_collection(
                        collection_name=self.collection
                    )
                except Exception:
                    raise create_error
                if not created_elsewhere:
                    raise

        # Serialize the has->create sequence within this process. The recheck
        # above handles the equivalent race across API replicas.
        async with self._collection_init_lock:
            await asyncio.to_thread(create_if_missing)

    async def ensure_seed(self, documents: list[dict[str, object]]) -> None:
        client = await self._get_client()

        def seed() -> None:
            records = [
                {
                    "id": str(document["id"]),
                    "vector": hash_embedding(f"{document['title']} {document['content']}"),
                    "title": str(document["title"]),
                    "content": str(document["content"]),
                    "source": str(document["source"]),
                    "status": "ACTIVE",
                }
                for document in documents
            ]
            client.upsert(collection_name=self.collection, data=records)

        async with asyncio.timeout(self.timeout_seconds * 3):
            await self._ensure_collection(client)
            await asyncio.to_thread(seed)

    async def search(self, query: str, limit: int = 3) -> list[SourceData]:
        client = await self._get_client()

        def perform_search() -> Any:
            return client.search(
                collection_name=self.collection,
                data=[hash_embedding(query)],
                limit=limit,
                output_fields=["title", "content", "source"],
                filter='status == "ACTIVE"',
                search_params={"metric_type": "COSINE", "params": {}},
            )

        async with asyncio.timeout(self.timeout_seconds):
            rows = await asyncio.to_thread(perform_search)
        hits = rows[0] if rows else []
        sources: list[SourceData] = []
        for hit in hits:
            entity = hit.get("entity", hit) if isinstance(hit, dict) else {}
            score = hit.get("distance") if isinstance(hit, dict) else None
            content = str(entity.get("content", ""))
            sources.append(
                SourceData(
                    kind="rag",
                    title=str(entity.get("title", "演示知识")),
                    reference=str(entity.get("source", f"milvus:{hit.get('id', '')}")),
                    excerpt=content[:600],
                    score=float(score) if score is not None else None,
                )
            )
        return sources

    async def _upsert_chunks(
        self, chunks: list[dict[str, str]], status: str
    ) -> None:
        if not chunks:
            return
        client = await self._get_client()

        def upsert() -> None:
            client.upsert(
                collection_name=self.collection,
                data=[
                    {
                        "id": item["id"][:64],
                        "vector": hash_embedding(f"{item['title']} {item['content']}"),
                        "title": item["title"][:200],
                        "content": item["content"],
                        "source": item["source"][:500],
                        "status": status,
                    }
                    for item in chunks
                ],
            )

        async with asyncio.timeout(self.timeout_seconds * 3):
            await self._ensure_collection(client)
            await asyncio.to_thread(upsert)

    async def index_chunks(self, chunks: list[dict[str, str]]) -> None:
        """Stage chunks invisibly; only ACTIVE vectors are searchable."""
        await self._upsert_chunks(chunks, "INDEXING")

    async def activate_chunks(self, chunks: list[dict[str, str]]) -> None:
        """Publish successfully persisted chunks to retrieval."""
        await self._upsert_chunks(chunks, "ACTIVE")

    async def delete_chunks(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        client = await self._get_client()

        def remove() -> None:
            if not client.has_collection(collection_name=self.collection):
                return
            client.delete(
                collection_name=self.collection,
                ids=[str(item)[:64] for item in chunk_ids],
            )

        async with asyncio.timeout(self.timeout_seconds):
            await asyncio.to_thread(remove)
