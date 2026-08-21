from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

import httpx

from app.cache import RetrievalCache
from app.config import Settings
from app.database import Database
from app.knowledge import DEMO_DOCUMENTS
from app.llm import LLMService
from app.mcp_client import MCPGovClient
from app.milvus import MilvusRAG
from app.schemas import HealthCheck


logger = logging.getLogger(__name__)


class AppServices:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.database = Database(settings.database_url)
        self.cache = RetrievalCache(settings.redis_url, settings.cache_ttl_seconds)
        self.milvus = MilvusRAG(
            settings.milvus_uri,
            settings.milvus_collection,
            settings.milvus_timeout_seconds,
        )
        self.mcp = MCPGovClient(
            settings.mcp_url,
            settings.mcp_health_url,
            settings.mcp_internal_token.get_secret_value(),
            settings.mcp_timeout_seconds,
        )
        self.llm = LLMService(
            settings.llm_mode,
            settings.llm_model,
            settings.deepseek_api_key.get_secret_value()
            if settings.deepseek_api_key is not None
            else None,
            settings.llm_timeout_seconds,
            settings.llm_max_retries,
        )
        self._http = httpx.AsyncClient(
            timeout=settings.dependency_health_timeout_seconds,
            trust_env=False,
        )
        self._seed_failures: set[str] = set()

    async def startup(self) -> None:
        if not self.settings.seed_on_startup:
            return
        outcomes = await asyncio.gather(
            self.database.seed_knowledge(DEMO_DOCUMENTS),
            self.milvus.ensure_seed(DEMO_DOCUMENTS),
            return_exceptions=True,
        )
        for name, outcome in zip(("postgres", "milvus"), outcomes, strict=True):
            if isinstance(outcome, BaseException):
                self._seed_failures.add(name)
                logger.warning("Startup seed for %s failed: %s", name, type(outcome).__name__)
            else:
                self._seed_failures.discard(name)

    async def shutdown(self) -> None:
        await asyncio.gather(
            self.cache.close(),
            self.database.dispose(),
            self._http.aclose(),
            return_exceptions=True,
        )

    async def _mock_api_ping(self) -> None:
        response = await self._http.get(
            f"{self.settings.mock_gov_api_url.rstrip('/')}/health"
        )
        response.raise_for_status()

    async def _postgres_ready(self) -> None:
        await self.database.ping()
        if self.settings.seed_on_startup and "postgres" in self._seed_failures:
            await self.database.seed_knowledge(DEMO_DOCUMENTS)
            self._seed_failures.discard("postgres")

    async def _milvus_ready(self) -> None:
        await self.milvus.ping()
        if self.settings.seed_on_startup and "milvus" in self._seed_failures:
            await self.milvus.ensure_seed(DEMO_DOCUMENTS)
            self._seed_failures.discard("milvus")

    async def readiness(self) -> dict[str, HealthCheck]:
        probes: dict[str, Callable[[], Awaitable[None]]] = {
            "postgres": self._postgres_ready,
            "redis": self.cache.ping,
            "milvus": self._milvus_ready,
            "mcp": self.mcp.ping,
            "mock_gov_api": self._mock_api_ping,
        }

        async def run_probe(probe: Callable[[], Awaitable[None]]) -> HealthCheck:
            started = time.perf_counter()
            try:
                async with asyncio.timeout(self.settings.dependency_health_timeout_seconds):
                    await probe()
                return HealthCheck(
                    status="ok",
                    latency_ms=round((time.perf_counter() - started) * 1000),
                )
            except Exception as exc:
                return HealthCheck(
                    status="error",
                    latency_ms=round((time.perf_counter() - started) * 1000),
                    detail=f"unavailable ({type(exc).__name__})",
                )

        results = await asyncio.gather(*(run_probe(probe) for probe in probes.values()))
        return dict(zip(probes.keys(), results, strict=True))
