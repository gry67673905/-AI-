from __future__ import annotations

import os

import pytest

from app.mcp_client import MCPGovClient


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_LIVE_MCP_TEST") != "1",
    reason="requires the local Node mock API and MCP integration servers",
)
async def test_python_client_calls_real_node_mcp_server() -> None:
    client = MCPGovClient(
        "http://127.0.0.1:13001/mcp",
        "http://127.0.0.1:13001/health",
        "integration-mcp-token",
        5,
    )

    sources, calls, warnings = await client.retrieve("办理社会保障卡需要准备哪些材料？")

    assert warnings == []
    assert [call.name for call in calls] == [
        "search_services",
        "get_service_details",
        "get_material_checklist",
    ]
    assert all(call.success for call in calls)
    assert len(sources) == 3
    assert all(source.kind == "mcp" for source in sources)

