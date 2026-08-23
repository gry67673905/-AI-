from __future__ import annotations

import asyncio
import math
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr


class EmbeddingConfigurationError(ValueError):
    pass


class EmbeddingUnavailable(RuntimeError):
    pass


def load_embedding_api_key(
    api_key: SecretStr | str | None,
    api_key_file: str | None,
) -> str:
    """Load a secret without putting its value into exceptions or repr output."""

    if api_key_file:
        path = Path(api_key_file)
        try:
            if not path.is_file() or path.stat().st_size > 4096:
                raise EmbeddingConfigurationError("embedding key file is invalid")
            value = path.read_text(encoding="utf-8").strip()
        except EmbeddingConfigurationError:
            raise
        except Exception as exc:
            raise EmbeddingConfigurationError(
                "embedding key file cannot be read"
            ) from exc
    elif isinstance(api_key, SecretStr):
        value = api_key.get_secret_value().strip()
    elif isinstance(api_key, str):
        value = api_key.strip()
    else:
        value = ""
    if not value or "\n" in value or "\r" in value:
        raise EmbeddingConfigurationError("embedding API key is not configured")
    return value


class DashScopeEmbeddingAdapter:
    """DashScope OpenAI-compatible embedding adapter with bounded retries."""

    batch_limit = 10

    def __init__(
        self,
        *,
        api_key: SecretStr | str | None,
        api_key_file: str | None = None,
        model_name: str = "text-embedding-v4",
        dimension: int = 1024,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if dimension <= 0:
            raise EmbeddingConfigurationError("embedding dimension must be positive")
        if max_retries < 0 or max_retries > 5:
            raise EmbeddingConfigurationError("embedding retries are out of range")
        self.model_name = model_name
        self.dimension = dimension
        self.max_retries = max_retries
        self._api_key = load_embedding_api_key(api_key, api_key_file)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            timeout=timeout_seconds,
            trust_env=False,
        )

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(model_name={self.model_name!r}, "
            f"dimension={self.dimension}, api_key=<redacted>)"
        )

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("embedding input must contain non-empty strings")
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_limit):
            vectors.extend(await self._embed_batch(texts[start:start + self.batch_limit]))
        return vectors

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        last_error: BaseException | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.post(
                    "embeddings",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self.model_name,
                        "input": texts,
                        "dimensions": self.dimension,
                    },
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise EmbeddingUnavailable(
                        f"embedding provider unavailable (status={response.status_code})"
                    )
                if not response.is_success:
                    raise EmbeddingUnavailable(
                        f"embedding request rejected (status={response.status_code})"
                    )
                return self._vectors(response.json(), len(texts))
            except (httpx.HTTPError, ValueError, EmbeddingUnavailable) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                await asyncio.sleep(min(0.25 * (2**attempt), 2.0))
        raise EmbeddingUnavailable("embedding request failed after bounded retries") from last_error

    def _vectors(self, payload: Any, expected: int) -> list[list[float]]:
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise EmbeddingUnavailable("embedding response schema is invalid")
        rows = sorted(
            payload["data"],
            key=lambda item: item.get("index", 0) if isinstance(item, dict) else 0,
        )
        vectors: list[list[float]] = []
        for row in rows:
            raw = row.get("embedding") if isinstance(row, dict) else None
            if not isinstance(raw, list) or len(raw) != self.dimension:
                raise EmbeddingUnavailable("embedding response dimension is invalid")
            try:
                vector = [float(item) for item in raw]
            except (TypeError, ValueError) as exc:
                raise EmbeddingUnavailable("embedding response vector is invalid") from exc
            if not all(math.isfinite(item) for item in vector):
                raise EmbeddingUnavailable("embedding response contains non-finite values")
            vectors.append(vector)
        if len(vectors) != expected:
            raise EmbeddingUnavailable("embedding response count is invalid")
        return vectors

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
