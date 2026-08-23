from __future__ import annotations

import asyncio
import json
import sys

from app.config import get_settings
from app.infrastructure.dashscope_embedding import DashScopeEmbeddingAdapter


async def run() -> int:
    settings = get_settings()
    adapter = DashScopeEmbeddingAdapter(
        api_key=settings.dashscope_api_key,
        api_key_file=settings.dashscope_api_key_file,
        model_name=settings.dashscope_embedding_model,
        dimension=settings.dashscope_embedding_dimension,
        base_url=settings.dashscope_embedding_base_url,
        timeout_seconds=settings.dashscope_embedding_timeout_seconds,
        max_retries=settings.dashscope_embedding_max_retries,
    )
    try:
        vectors = await adapter.embed_texts(["智慧政务演示连通性检查"])
        if len(vectors) != 1 or len(vectors[0]) != adapter.dimension:
            raise RuntimeError("embedding validation returned an invalid shape")
        print(
            json.dumps(
                {
                    "status": "OK",
                    "model": adapter.model_name,
                    "dimension": adapter.dimension,
                    "requests": 1,
                    "vectors_printed": 0,
                    "secret_printed": False,
                },
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        await adapter.close()


def main() -> None:
    try:
        raise SystemExit(asyncio.run(run()))
    except Exception as exc:
        print(f"RAG embedding check failed ({type(exc).__name__})", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
