from __future__ import annotations

import asyncio
from typing import Any

from app.knowledge import EMBEDDING_DIMENSION, hash_embedding
from app.schemas import Source


class MilvusRAG:
    def __init__(self, uri: str, collection: str, timeout_seconds: float):
        self.uri = uri
        self.collection = collection
        self.timeout_seconds = timeout_seconds
        self._client: Any = None
        self._client_lock = asyncio.Lock()

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

    async def ensure_seed(self, documents: list[dict[str, object]]) -> None:
        client = await self._get_client()

        def seed() -> None:
            if not client.has_collection(collection_name=self.collection):
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
            records = [
                {
                    "id": str(document["id"]),
                    "vector": hash_embedding(f"{document['title']} {document['content']}"),
                    "title": str(document["title"]),
                    "content": str(document["content"]),
                    "source": str(document["source"]),
                }
                for document in documents
            ]
            client.upsert(collection_name=self.collection, data=records)

        async with asyncio.timeout(self.timeout_seconds * 3):
            await asyncio.to_thread(seed)

    async def search(self, query: str, limit: int = 3) -> list[Source]:
        client = await self._get_client()

        def perform_search() -> Any:
            return client.search(
                collection_name=self.collection,
                data=[hash_embedding(query)],
                limit=limit,
                output_fields=["title", "content", "source"],
                search_params={"metric_type": "COSINE", "params": {}},
            )

        async with asyncio.timeout(self.timeout_seconds):
            rows = await asyncio.to_thread(perform_search)
        hits = rows[0] if rows else []
        sources: list[Source] = []
        for hit in hits:
            entity = hit.get("entity", hit) if isinstance(hit, dict) else {}
            score = hit.get("distance") if isinstance(hit, dict) else None
            content = str(entity.get("content", ""))
            sources.append(
                Source(
                    kind="rag",
                    title=str(entity.get("title", "演示知识")),
                    reference=str(entity.get("source", f"milvus:{hit.get('id', '')}")),
                    excerpt=content[:600],
                    score=float(score) if score is not None else None,
                )
            )
        return sources
