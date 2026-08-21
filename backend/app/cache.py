from __future__ import annotations

import hashlib
import json

from redis.asyncio import Redis

from app.knowledge import normalize_text
from app.schemas import Source, ToolCall


class RetrievalCache:
    def __init__(self, url: str, ttl_seconds: int):
        self.client = Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def key_for(message: str) -> str:
        digest = hashlib.sha256(normalize_text(message).encode("utf-8")).hexdigest()
        return f"smart-gov:retrieval:v1:{digest}"

    async def ping(self) -> None:
        if not await self.client.ping():
            raise RuntimeError("Redis ping failed")

    async def get(self, message: str) -> tuple[list[Source], list[ToolCall]] | None:
        raw = await self.client.get(self.key_for(message))
        if raw is None:
            return None
        payload = json.loads(raw)
        sources = [Source.model_validate(item) for item in payload.get("sources", [])]
        calls = [ToolCall.model_validate({**item, "cached": True}) for item in payload.get("tool_calls", [])]
        return sources, calls

    async def set(self, message: str, sources: list[Source], tool_calls: list[ToolCall]) -> None:
        payload = {
            "sources": [source.model_dump(mode="json") for source in sources],
            "tool_calls": [call.model_dump(mode="json", exclude={"cached"}) for call in tool_calls],
        }
        await self.client.setex(
            self.key_for(message),
            self.ttl_seconds,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )

    async def close(self) -> None:
        await self.client.aclose()

