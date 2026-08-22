from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

from app.application.dtos import SourceData, ToolCallData
from app.security import redact_pii_text, redact_sensitive


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
        (("劳动合同备案", "劳动合同", "合同备案"), "劳动合同"),
        (("企业社会保险", "企业社保", "单位社保"), "企业社会保险"),
        (("个体工商户", "个体户", "个体注册"), "个体工商户"),
        (("住房公积金", "公积金"), "住房公积金"),
        (("社会保障卡", "社保卡"), "社会保障卡"),
        (("居民身份证", "身份证"), "身份证"),
        (("营业执照", "执照"), "营业执照"),
    )
    for aliases, keyword in demo_aliases:
        if any(alias in normalized for alias in aliases):
            return keyword
    return redact_pii_text(normalized)[:100]


def _service_candidates(value: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if isinstance(value, dict):
        identifier = _extract_positive_id({key: value.get(key) for key in ("id", "serviceId", "service_id", "itemId", "item_id")})
        name = next((value.get(key) for key in ("name", "title", "item_name", "service_name") if isinstance(value.get(key), str)), None)
        if identifier is not None and name:
            candidates.append(value)
        for child in value.values():
            candidates.extend(_service_candidates(child))
    elif isinstance(value, list):
        for child in value:
            candidates.extend(_service_candidates(child))
    return candidates


def select_service(
    result: Any, query: str, keyword: str
) -> tuple[int | None, bool, list[dict[str, Any]]]:
    """Return the best item, explicitly surfacing low-confidence ambiguity."""
    candidates = _service_candidates(result)
    if not candidates:
        return _extract_positive_id(result), False, []
    normalized = query.strip()
    intents = (
        (("劳动合同", "合同备案"), ("劳动合同",)),
        (("企业社保", "企业社会保险", "单位社保"), ("企业", "社会保险")),
        (("个体户", "个体工商户", "个体注册"), ("个体工商户",)),
        (("公积金",), ("公积金",)),
        (("社保卡", "社会保障卡"), ("社会保障卡",)),
        (("身份证",), ("身份证",)),
    )
    required = next((terms for aliases, terms in intents if any(alias in normalized for alias in aliases)), (keyword,))
    query_terms = [term for term in ("企业", "劳动", "合同", "个体", "社会保险", "社保卡", "身份证", "公积金") if term in normalized]

    def score(item: dict[str, Any]) -> tuple[int, int]:
        text = " ".join(str(item.get(key, "")) for key in ("name", "title", "code", "category", "summary"))
        direct = sum(100 for term in required if term and term in text)
        contextual = sum(10 for term in query_terms if term in text)
        identifier = _extract_positive_id(item) or 0
        return direct + contextual, -identifier

    ranked = sorted(candidates, key=score, reverse=True)
    top_score = score(ranked[0])[0]
    second_score = score(ranked[1])[0] if len(ranked) > 1 else -1000
    ambiguous = len(ranked) > 1 and (top_score <= 0 or top_score - second_score < 50)
    if ambiguous:
        return None, True, ranked[:2]
    return _extract_positive_id(ranked[0]), False, []


def select_service_id(result: Any, query: str, keyword: str) -> int | None:
    return select_service(result, query, keyword)[0]


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

    async def retrieve(
        self,
        query: str,
        selected_service_id: int | None = None,
        allow_inferred_details: bool = True,
    ) -> tuple[list[SourceData], list[ToolCallData], list[str]]:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        calls: list[ToolCallData] = []
        warnings: list[str] = []
        clarification_candidates: list[dict[str, Any]] = []
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

                        if selected_service_id is not None:
                            service_id, ambiguous, clarification_candidates = (
                                selected_service_id,
                                False,
                                [],
                            )
                        elif allow_inferred_details:
                            service_id, ambiguous, clarification_candidates = select_service(
                                search_call.result, query, keyword
                            )
                        else:
                            service_id, ambiguous, clarification_candidates = None, False, []
                        if ambiguous:
                            warnings.append("clarification_required: 找到多个可能事项，请选择后再查询材料、流程和窗口")
                        if service_id is not None:
                            details_call, checklist_call, process_call, window_call = await asyncio.gather(
                                self._call_tool(session, "get_service_details", {"id": service_id}),
                                self._call_tool(session, "get_material_checklist", {"itemId": service_id}),
                                self._call_tool(session, "get_process_navigation", {"itemId": service_id}),
                                self._call_tool(session, "get_window_info", {"itemId": service_id}),
                            )
                            calls.extend((details_call, checklist_call, process_call, window_call))
                            if not all(call.success for call in (details_call, checklist_call, process_call, window_call)):
                                warnings.append("mcp_tool_failed: 部分政务事项详情获取失败")

        sources = [
            SourceData(
                kind="mcp",
                title={
                    "search_services": "政务事项检索（演示）",
                    "get_service_details": "政务事项详情（演示）",
                    "get_material_checklist": "办理材料清单（演示）",
                    "get_process_navigation": "办理流程导航（演示）",
                    "get_window_info": "服务窗口信息（演示）",
                }.get(call.name, call.name),
                reference=f"mcp:{call.name}",
                excerpt=_compact_excerpt(call.result),
            )
            for call in calls
            if call.success and call.result is not None
            and not (call.name == "search_services" and clarification_candidates)
        ]
        sources.extend(
            SourceData(
                kind="mcp",
                title=f"候选事项：{item.get('name', item.get('title', '未命名事项'))}（演示）",
                reference=f"mcp:search_services:{_extract_positive_id(item) or 'candidate'}",
                excerpt=_compact_excerpt(item),
            )
            for item in clarification_candidates
        )
        return sources, calls, warnings

    async def _call_tool(self, session: Any, name: str, arguments: dict[str, Any]) -> ToolCallData:
        started = time.perf_counter()
        try:
            result = await session.call_tool(name, arguments=arguments)
            payload = decode_tool_result(result)
            is_error = bool(
                getattr(result, "isError", getattr(result, "is_error", False))
            )
            return ToolCallData(
                name=name,
                success=not is_error,
                arguments=arguments,
                result=payload,
                duration_ms=round((time.perf_counter() - started) * 1000),
                error="MCP tool returned an error" if is_error else None,
            )
        except Exception as exc:
            return ToolCallData(
                name=name,
                success=False,
                arguments=arguments,
                duration_ms=round((time.perf_counter() - started) * 1000),
                error=str(redact_sensitive(str(exc)))[:300],
            )
