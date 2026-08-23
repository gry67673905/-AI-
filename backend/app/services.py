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
from app.quota import ChatQuota
from app.infrastructure.composite_retriever import CompositeKnowledgeRetriever
from app.infrastructure.dashscope_embedding import DashScopeEmbeddingAdapter
from app.infrastructure.rag_corpus_milvus import (
    GroupCorpusRetriever,
    VersionedMilvusCorpusIndex,
)
from app.application.rag_import import versioned_collection_names
from app.infrastructure.runtime import BusinessRuntime


logger = logging.getLogger(__name__)


class AppServices:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.database = Database(settings.database_url)
        self.cache = RetrievalCache(
            settings.redis_url,
            settings.cache_ttl_seconds,
            dataset_version=settings.rag_dataset_version,
        )
        self.milvus = MilvusRAG(
            settings.milvus_uri,
            settings.milvus_collection,
            settings.milvus_timeout_seconds,
        )
        self.group_embedding: DashScopeEmbeddingAdapter | None = None
        self.group_index: VersionedMilvusCorpusIndex | None = None
        self.group_retriever: GroupCorpusRetriever | None = None
        if settings.rag_group_enabled:
            self.group_embedding = DashScopeEmbeddingAdapter(
                api_key=settings.dashscope_api_key,
                api_key_file=settings.dashscope_api_key_file,
                model_name=settings.dashscope_embedding_model,
                dimension=settings.dashscope_embedding_dimension,
                base_url=settings.dashscope_embedding_base_url,
                timeout_seconds=settings.dashscope_embedding_timeout_seconds,
                max_retries=settings.dashscope_embedding_max_retries,
            )
            self.group_index = VersionedMilvusCorpusIndex(
                settings.milvus_uri,
                settings.milvus_timeout_seconds,
                settings.dashscope_embedding_dimension,
            )
            self.group_retriever = GroupCorpusRetriever(
                self.group_index,
                self.group_embedding,
                dataset_version=settings.rag_dataset_version,
                collection_alias=settings.rag_group_collection_alias,
                route_alias=settings.rag_group_route_alias,
            )
        self.knowledge_retriever = CompositeKnowledgeRetriever(
            self.milvus, self.group_retriever
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
        self.chat_quota = ChatQuota(
            settings.redis_url,
            settings.pii_hmac_key.get_secret_value(),
            enabled=settings.chat_quota_enabled,
            anonymous_daily=settings.chat_quota_anonymous_daily,
            authenticated_daily=settings.chat_quota_authenticated_daily,
            global_daily=settings.chat_quota_global_daily,
        )
        self.business = BusinessRuntime(
            settings,
            self.database.sessions,
            self.database,
            self.cache,
            self.mcp,
            self.milvus,
            self.llm,
            knowledge_retrieval=self.knowledge_retriever,
        )
        self._http = httpx.AsyncClient(
            timeout=settings.dependency_health_timeout_seconds,
            trust_env=False,
        )
        self._seed_failures: set[str] = set()
        self._seed_retry_lock = asyncio.Lock()
        self._seed_retry_tasks: dict[str, asyncio.Task[None]] = {}

    async def startup(self) -> None:
        if not self.settings.seed_on_startup:
            return
        outcomes = await asyncio.gather(
            self.database.seed_knowledge(DEMO_DOCUMENTS),
            self.milvus.ensure_seed(DEMO_DOCUMENTS),
            self.business.startup(),
            return_exceptions=True,
        )
        for name, outcome in zip(("postgres", "milvus", "business"), outcomes, strict=True):
            if isinstance(outcome, BaseException):
                self._seed_failures.add(name)
                logger.warning("Startup seed for %s failed: %s", name, type(outcome).__name__)
            else:
                self._seed_failures.discard(name)

    async def shutdown(self) -> None:
        tasks = [
            self.cache.close(),
            self.chat_quota.close(),
            self.database.dispose(),
            self._http.aclose(),
        ]
        if self.group_embedding is not None:
            tasks.append(self.group_embedding.close())
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _mock_api_ping(self) -> None:
        response = await self._http.get(
            f"{self.settings.mock_gov_api_url.rstrip('/')}/health"
        )
        response.raise_for_status()

    async def _postgres_ready(self) -> None:
        await self.database.ping()
        await self._retry_failed_seed(
            "postgres", lambda: self.database.seed_knowledge(DEMO_DOCUMENTS)
        )

    async def _milvus_ready(self) -> None:
        await self.milvus.ping()
        await self._retry_failed_seed(
            "milvus", lambda: self.milvus.ensure_seed(DEMO_DOCUMENTS)
        )

    async def _rag_corpus_ready(self) -> None:
        if self.group_index is None or not self.settings.rag_archive_sha256:
            raise RuntimeError("group RAG readiness configuration is incomplete")
        collection, route_collection = versioned_collection_names(
            self.settings.rag_group_collection_prefix,
            self.settings.rag_dataset_version,
            self.settings.rag_archive_sha256,
        )
        await self.group_index.ping_active(
            collection_alias=self.settings.rag_group_collection_alias,
            route_alias=self.settings.rag_group_route_alias,
            expected_collection=collection,
            expected_route_collection=route_collection,
            expected_chunk_count=self.settings.rag_expected_chunk_count,
            expected_route_count=self.settings.rag_expected_route_count,
        )

    async def _business_ready(self) -> None:
        # Business startup includes the catalogue/accounts seed and MinIO bucket
        # creation. A transient startup failure must remain visible and retryable;
        # a healthy object-store socket alone is not sufficient readiness.
        await self.business.object_store.ping()
        await self._retry_failed_seed("business", self.business.startup)

    def _ensure_seed_retry_state(self) -> None:
        """Initialize retry state for lightweight test doubles made via ``__new__``."""
        if not hasattr(self, "_seed_retry_lock"):
            self._seed_retry_lock = asyncio.Lock()
        if not hasattr(self, "_seed_retry_tasks"):
            self._seed_retry_tasks = {}

    @staticmethod
    def _observe_seed_task(task: asyncio.Task[None]) -> None:
        """Retrieve background exceptions when a readiness waiter times out."""
        if not task.cancelled():
            task.exception()

    async def _run_seed_retry(
        self,
        name: str,
        operation: Callable[[], Awaitable[None]],
    ) -> None:
        succeeded = False
        try:
            await operation()
            succeeded = True
        finally:
            async with self._seed_retry_lock:
                if succeeded:
                    self._seed_failures.discard(name)
                else:
                    self._seed_failures.add(name)
                current = asyncio.current_task()
                if self._seed_retry_tasks.get(name) is current:
                    self._seed_retry_tasks.pop(name, None)

    async def _retry_failed_seed(
        self,
        name: str,
        operation: Callable[[], Awaitable[None]],
    ) -> None:
        if not self.settings.seed_on_startup:
            return
        self._ensure_seed_retry_state()
        async with self._seed_retry_lock:
            if name not in self._seed_failures:
                return
            task = self._seed_retry_tasks.get(name)
            if task is None:
                task = asyncio.create_task(
                    self._run_seed_retry(name, operation),
                    name=f"seed-retry-{name}",
                )
                task.add_done_callback(self._observe_seed_task)
                self._seed_retry_tasks[name] = task

        # A probe timeout must not cancel the shared retry for all other waiters.
        await asyncio.shield(task)

    async def readiness(self) -> dict[str, HealthCheck]:
        probes: dict[str, Callable[[], Awaitable[None]]] = {
            "postgres": self._postgres_ready,
            "redis": self.cache.ping,
            "milvus": self._milvus_ready,
            "mcp": self.mcp.ping,
            "mock_gov_api": self._mock_api_ping,
            "minio": self.business.object_store.ping,
            "business_seed": self._business_ready,
        }
        if self.settings.rag_group_enabled:
            probes["rag_corpus"] = self._rag_corpus_ready

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
