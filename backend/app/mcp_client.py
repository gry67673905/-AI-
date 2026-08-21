from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

from app.schemas import Source, ToolCall
from app.security import redact_sensitive


def decode_tool_result(result: Any) -> Any:
    """Decode one MCP content layer; intentionally never parses nested JSON strings twice."""

    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    if structured is not None:
        return redact_sensitive(structured)

    texts = [
        item.text
        for item in (getattr(result, "content", None) or [])
        if isinstance(getattr(item, "text", None), str)
    ]
    if len(texts) == 1:
        try:
            return redact_sensitive(json.loads(texts[0]))
        except json.JSONDecodeError:
            return redact_sensitive(texts[0])
    return redact_sensitive(texts)


def _extract_positive_id(value: Any) -> int | None:
    if isinstance(value, dict):
        for key in ("id", "serviceId", "service_id", "itemId", "item_id"):
            candidate = value.get(key)
            if isinstance(candidate, int) and not isinstance(candidate, bool) and candidate > 0:
                return candidate
            if isinstance(candidate, str) and candidate.isdigit() and int(candidate) > 0:
                return int(candidate)
        for child in value.values():
            candidate = _extract_positive_id(child)
            if candidate is not None:
                return candidate
    elif isinstance(value, list):
        for child in value:
            candidate = _extract_positive_id(child)
            if candidate is not None:
                return candidate
    return None


def _compact_excerpt(value: Any, limit: int = 600) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return text[:limit]


def normalize_mcp_keyword(query: str) -> str:
    """Match the reused MCP package's 1-100 character keyword contract."""

    normalized = query.strip()
    demo_aliases = (
        (("社会保障卡", "社保卡"), "社会保障卡"),
        (("居民身份证", "身份证"), "身份证"),
        (("营业执照", "执照"), "营业执照"),
    )
    for aliases, keyword in demo_aliases:
        if any(alias in normalized for alias in aliases):
            return keyword
    return normalized[:100]


class MCPGovClient:
    def __init__(self, url: str, health_url: str, token: str, timeout_seconds: float):
        self.url = url
        self.health_url = health_url
        self.token = token
        self.timeout_seconds = timeout_seconds

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    async def ping(self) -> None:
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds, trust_env=False
        ) as client:
            response = await client.get(self.health_url, headers=self.headers)
            response.raise_for_status()

    async def retrieve(self, query: str) -> tuple[list[Source], list[ToolCall], list[str]]:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        calls: list[ToolCall] = []
        warnings: list[str] = []
        keyword = normalize_mcp_keyword(query)
        async with asyncio.timeout(self.timeout_seconds * 3):
            async with httpx.AsyncClient(
                headers=self.headers,
                timeout=httpx.Timeout(self.timeout_seconds),
                trust_env=False,
            ) as http_client:
                async with streamable_http_client(
                    self.url, http_client=http_client
                ) as (read_stream, write_stream, _):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        search_call = await self._call_tool(
                            session, "search_services", {"keyword": keyword}
                        )
                        calls.append(search_call)
                        if not search_call.success:
                            warnings.append("mcp_tool_failed: 政务事项检索失败")
                            return [], calls, warnings

                        service_id = _extract_positive_id(search_call.result)
                        if service_id is not None:
                            details_call = await self._call_tool(
                                session, "get_service_details", {"id": service_id}
                            )
                            checklist_call = await self._call_tool(
                                session, "get_material_checklist", {"itemId": service_id}
                            )
                            calls.extend((details_call, checklist_call))
                            if not details_call.success or not checklist_call.success:
                                warnings.append("mcp_tool_failed: 部分政务事项详情获取失败")

        sources = [
            Source(
                kind="mcp",
                title={
                    "search_services": "政务事项检索（演示）",
                    "get_service_details": "政务事项详情（演示）",
                    "get_material_checklist": "办理材料清单（演示）",
                }.get(call.name, call.name),
                reference=f"mcp:{call.name}",
                excerpt=_compact_excerpt(call.result),
            )
            for call in calls
            if call.success and call.result is not None
        ]
        return sources, calls, warnings

    async def _call_tool(self, session: Any, name: str, arguments: dict[str, Any]) -> ToolCall:
        started = time.perf_counter()
        try:
            result = await session.call_tool(name, arguments=arguments)
            payload = decode_tool_result(result)
            is_error = bool(
                getattr(result, "isError", getattr(result, "is_error", False))
            )
            return ToolCall(
                name=name,
                success=not is_error,
                arguments=arguments,
                result=payload,
                duration_ms=round((time.perf_counter() - started) * 1000),
                error="MCP tool returned an error" if is_error else None,
            )
        except Exception as exc:
            return ToolCall(
                name=name,
                success=False,
                arguments=arguments,
                duration_ms=round((time.perf_counter() - started) * 1000),
                error=str(redact_sensitive(str(exc)))[:300],
            )
