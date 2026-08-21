from __future__ import annotations

import asyncio
from uuid import uuid4

from app.errors import LLMUnavailable
from app.schemas import ChatRequest, ChatResponse, Source, ToolCall


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


async def handle_chat(payload: ChatRequest, services: object) -> ChatResponse:
    request_id = uuid4()
    session_id = payload.session_id or uuid4()
    await services.database.save_user_message(session_id, request_id, payload.message)

    warnings: list[str] = []
    cache_hit = False
    sources: list[Source] = []
    tool_calls: list[ToolCall] = []

    try:
        cached = await services.cache.get(payload.message)
    except Exception:
        cached = None
        warnings.append("redis_unavailable: 缓存服务暂不可用，已绕过缓存")

    if cached is not None:
        cache_hit = True
        sources, tool_calls = cached
    else:
        mcp_result, rag_result = await asyncio.gather(
            services.mcp.retrieve(payload.message),
            services.milvus.search(payload.message),
            return_exceptions=True,
        )
        if isinstance(mcp_result, BaseException):
            warnings.append("mcp_unavailable: 政务工具服务暂不可用")
        else:
            mcp_sources, tool_calls, mcp_warnings = mcp_result
            sources.extend(mcp_sources)
            warnings.extend(mcp_warnings)
        if isinstance(rag_result, BaseException):
            warnings.append("milvus_unavailable: 知识检索服务暂不可用")
        else:
            sources.extend(rag_result)

        if not warnings:
            try:
                await services.cache.set(payload.message, sources, tool_calls)
            except Exception:
                warnings.append("redis_unavailable: 缓存服务暂不可用，已绕过缓存")

    try:
        answer = await services.llm.answer(
            payload.message, sources, tool_calls, request_id=request_id
        )
    except LLMUnavailable:
        raise
    except Exception as exc:
        raise LLMUnavailable(request_id) from exc

    warnings = _deduplicate(warnings)
    await services.database.save_assistant_result(
        session_id,
        request_id,
        answer,
        sources,
        tool_calls,
        cache_hit,
        warnings,
    )
    return ChatResponse(
        request_id=request_id,
        session_id=session_id,
        answer=answer,
        sources=sources,
        tool_calls=tool_calls,
        cache_hit=cache_hit,
        warnings=warnings,
    )

