from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from redis.asyncio import Redis

from app.knowledge import normalize_text
from app.application.dtos import SourceData, ToolCallData
from app.security import redact_pii_text, redact_sensitive


class RetrievalCache:
    def __init__(
        self, url: str, ttl_seconds: int, dataset_version: str = "none"
    ):
        self.client = Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        self.ttl_seconds = ttl_seconds
        self.dataset_version = (dataset_version or "none").strip()[:64]

    @staticmethod
    def key_for(
        message: str,
        public_context_id: str | int | None = None,
        dataset_version: str = "none",
    ) -> str:
        normalized = (
            f"{normalize_text(message)}|service:{public_context_id or 'none'}"
            f"|dataset:{(dataset_version or 'none').strip()[:64]}"
        )
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return f"smart-gov:retrieval:v3:{digest}"

    async def ping(self) -> None:
        if not await self.client.ping():
            raise RuntimeError("Redis ping failed")

    async def get(self, message: str, public_context_id: str | int | None = None) -> tuple[list[SourceData], list[ToolCallData]] | None:
        raw = await self.client.get(
            self.key_for(message, public_context_id, self.dataset_version)
        )
        if raw is None:
            return None
        payload = json.loads(raw)
        sources = [SourceData(**item) for item in payload.get("sources", [])]
        calls = [
            ToolCallData(**{**item, "cached": True})
            for item in payload.get("tool_calls", [])
        ]
        return sources, calls

    async def set(self, message: str, sources: list[SourceData], tool_calls: list[ToolCallData], public_context_id: str | int | None = None) -> None:
        payload = {
            "sources": [
                {
                    **asdict(source),
                    "excerpt": redact_pii_text(source.excerpt),
                }
                for source in sources
            ],
            # Public retrieval cache deliberately omits invocation arguments.
            # They are not needed to replay a display-only result and could
            # otherwise retain user-supplied identifiers in Redis.
            "tool_calls": [
                {
                    **{
                        key: value
                        for key, value in asdict(call).items()
                        if key not in {"cached", "arguments"}
                    },
                    "arguments": {},
                    "result": redact_sensitive(call.result),
                }
                for call in tool_calls
            ],
        }
        await self.client.setex(
            self.key_for(message, public_context_id, self.dataset_version),
            self.ttl_seconds,
            json.dumps(
                payload, ensure_ascii=False, separators=(",", ":"), default=str
            ),
        )

    async def invalidate_public(self) -> None:
        """Invalidate only public retrieval context after knowledge changes."""
        keys = [
            key
            async for key in self.client.scan_iter(
                match="smart-gov:retrieval:v3:*", count=200
            )
        ]
        if keys:
            await self.client.delete(*keys)

    async def close(self) -> None:
        await self.client.aclose()
