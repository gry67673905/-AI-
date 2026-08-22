from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import asdict
from typing import Any
from uuid import UUID

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.errors import (
    AuthenticationRequired,
    ConflictError,
    DatabaseUnavailable,
    PermissionDenied,
    ServiceError,
)
from app.knowledge import content_hash
from app.models import ChatMessage, ChatSession, KnowledgeDocument, ToolAudit
from app.application.dtos import SourceData, ToolCallData
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
        if not documents:
            return
        table = KnowledgeDocument.__table__
        values = [
            {
                "id": str(document["id"]),
                "title": str(document["title"]),
                "content": str(document["content"]),
                "source": str(document["source"]),
                "content_hash": content_hash(str(document["content"])),
                "metadata": dict(document.get("metadata", {})),
            }
            for document in documents
        ]
        statement = postgresql_insert(table).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=[table.c.id],
            set_={
                "title": statement.excluded.title,
                "content": statement.excluded.content,
                "source": statement.excluded.source,
                "content_hash": statement.excluded.content_hash,
                "metadata": statement.excluded.metadata,
                "updated_at": func.now(),
            },
        )
        async with self.sessions.begin() as session:
            # PostgreSQL performs the conflict decision atomically, so concurrent
            # API replicas can seed the same legacy documents without a
            # check-then-insert race.
            await session.execute(statement)

    async def save_user_message(
        self,
        session_id: UUID,
        request_id: UUID,
        message: str,
        owner_account_id: UUID | None = None,
    ) -> None:
        try:
            async with self.sessions.begin() as session:
                # SELECT ... FOR UPDATE cannot lock a row that does not yet
                # exist. Serialize the create/owner-check/message-write unit by
                # session UUID so concurrent first messages cannot race on the
                # chat_sessions primary key or cross-claim ownership.
                engine = getattr(self, "engine", None)
                dialect_name = getattr(
                    getattr(engine, "dialect", None), "name", None
                )
                if dialect_name == "postgresql":
                    await session.execute(
                        text(
                            "SELECT pg_advisory_xact_lock("
                            "hashtextextended(:lock_name, 0))"
                        ),
                        {"lock_name": f"smart-gov:chat-session:{session_id}"},
                    )
                chat_session = await session.get(ChatSession, session_id, with_for_update=True)
                if chat_session is None:
                    chat_session = ChatSession(
                        id=session_id, owner_account_id=owner_account_id
                    )
                    session.add(chat_session)
                    await session.flush()
                else:
                    if chat_session.owner_account_id is not None:
                        if owner_account_id is None:
                            raise AuthenticationRequired("该咨询会话已归属账号，请先登录")
                        if chat_session.owner_account_id != owner_account_id:
                            raise PermissionDenied("咨询会话不属于当前账号")
                    elif owner_account_id is not None:
                        raise ConflictError(
                            "旧匿名咨询不能自动归属账号，请新建登录会话",
                            "anonymous_session_not_claimable",
                        )
                    # Legacy anonymous sessions deliberately remain anonymous.
                    # Logging in with the same UUID must never auto-attribute old
                    # messages to the newly authenticated account.
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
        except ServiceError:
            raise
        except Exception as exc:
            raise DatabaseUnavailable(request_id) from exc

    async def save_assistant_result(
        self,
        session_id: UUID,
        request_id: UUID,
        answer: str,
        sources: list[SourceData],
        tool_calls: list[ToolCallData],
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
                            "sources": [asdict(source) for source in sources],
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
