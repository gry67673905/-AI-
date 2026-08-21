from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.errors import DatabaseUnavailable
from app.knowledge import content_hash
from app.models import ChatMessage, ChatSession, KnowledgeDocument, ToolAudit
from app.schemas import Source, ToolCall
from app.security import redact_sensitive


class Database:
    def __init__(self, url: str):
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def ping(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def seed_knowledge(self, documents: list[dict[str, object]]) -> None:
        async with self.sessions.begin() as session:
            for document in documents:
                document_id = str(document["id"])
                existing = await session.get(KnowledgeDocument, document_id)
                values = {
                    "title": str(document["title"]),
                    "content": str(document["content"]),
                    "source": str(document["source"]),
                    "content_hash": content_hash(str(document["content"])),
                    "metadata_json": dict(document.get("metadata", {})),
                }
                if existing is None:
                    session.add(KnowledgeDocument(id=document_id, **values))
                else:
                    for key, value in values.items():
                        setattr(existing, key, value)

    async def save_user_message(
        self, session_id: UUID, request_id: UUID, message: str
    ) -> None:
        try:
            async with self.sessions.begin() as session:
                chat_session = await session.get(ChatSession, session_id)
                if chat_session is None:
                    chat_session = ChatSession(id=session_id)
                    session.add(chat_session)
                    await session.flush()
                else:
                    chat_session.updated_at = datetime.now(timezone.utc)
                session.add(
                    ChatMessage(
                        session_id=session_id,
                        request_id=request_id,
                        role="user",
                        content=message,
                        extra={},
                    )
                )
        except Exception as exc:
            raise DatabaseUnavailable(request_id) from exc

    async def save_assistant_result(
        self,
        session_id: UUID,
        request_id: UUID,
        answer: str,
        sources: list[Source],
        tool_calls: list[ToolCall],
        cache_hit: bool,
        warnings: list[str],
    ) -> None:
        try:
            async with self.sessions.begin() as session:
                chat_session = await session.get(ChatSession, session_id)
                if chat_session is None:
                    raise RuntimeError("chat session disappeared")
                chat_session.updated_at = datetime.now(timezone.utc)
                session.add(
                    ChatMessage(
                        session_id=session_id,
                        request_id=request_id,
                        role="assistant",
                        content=answer,
                        extra={
                            "sources": [source.model_dump(mode="json") for source in sources],
                            "cache_hit": cache_hit,
                            "warnings": warnings,
                        },
                    )
                )
                for call in tool_calls:
                    if call.cached:
                        continue
                    safe_arguments = redact_sensitive(call.arguments)
                    safe_result = redact_sensitive(call.result)
                    session.add(
                        ToolAudit(
                            request_id=request_id,
                            session_id=session_id,
                            tool_name=call.name,
                            arguments=safe_arguments,
                            result=safe_result,
                            success=call.success,
                            duration_ms=call.duration_ms,
                            error=redact_sensitive(call.error),
                        )
                    )
        except DatabaseUnavailable:
            raise
        except Exception as exc:
            raise DatabaseUnavailable(request_id) from exc
