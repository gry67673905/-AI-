from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.infrastructure.dashscope_embedding import (
    DashScopeEmbeddingAdapter,
    EmbeddingUnavailable,
)


@pytest.mark.asyncio
async def test_dashscope_embedding_uses_key_file_without_exposing_secret(
    tmp_path: Path,
) -> None:
    secret = "synthetic-secret-value"
    key_file = tmp_path / "embedding-key"
    key_file.write_text(secret, encoding="utf-8")
    seen_authorization = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_authorization
        seen_authorization = request.headers["Authorization"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [1, 0, 0, 0]},
                    {"index": 1, "embedding": [0, 1, 0, 0]},
                ]
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.test/v1/"
    )
    adapter = DashScopeEmbeddingAdapter(
        api_key="ignored",
        api_key_file=str(key_file),
        model_name="fake-embedding",
        dimension=4,
        max_retries=0,
        client=client,
    )
    try:
        vectors = await adapter.embed_texts(["材料", "流程"])
    finally:
        await client.aclose()

    assert vectors == [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]]
    assert seen_authorization == f"Bearer {secret}"
    assert secret not in repr(adapter)


@pytest.mark.asyncio
async def test_dashscope_error_never_reflects_provider_body_or_key() -> None:
    secret = "synthetic-secret-value"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"provider echoed {secret}")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.test/v1/"
    )
    adapter = DashScopeEmbeddingAdapter(
        api_key=secret,
        dimension=4,
        max_retries=0,
        client=client,
    )
    try:
        with pytest.raises(EmbeddingUnavailable) as error:
            await adapter.embed_texts(["测试"])
    finally:
        await client.aclose()

    assert secret not in str(error.value)
    assert "provider echoed" not in str(error.value)
