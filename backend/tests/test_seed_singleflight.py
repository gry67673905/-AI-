from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Any

import pytest
from minio.error import S3Error
from sqlalchemy.dialects import postgresql

from app.database import Database
from app.errors import ConflictError, DependencyUnavailable
from app.infrastructure.object_store import MinioObjectStore
from app.milvus import MilvusRAG
from app.services import AppServices


@pytest.mark.asyncio
async def test_minio_bucket_create_race_is_tolerated_only_after_recheck() -> None:
    class Client:
        def __init__(self) -> None:
            self.exists_calls: dict[str, int] = {}

        def bucket_exists(self, bucket: str) -> bool:
            calls = self.exists_calls.get(bucket, 0) + 1
            self.exists_calls[bucket] = calls
            # Missing at the first probe; the competing replica owns it by the
            # time the create error is handled.
            return calls > 1

        def make_bucket(self, bucket: str) -> None:
            raise S3Error(
                None, "BucketAlreadyOwnedByYou", "created concurrently",
                bucket, "request", "host", bucket_name=bucket,
            )

    store = object.__new__(MinioObjectStore)
    store._client = Client()  # type: ignore[attr-defined]
    store.materials_bucket = "materials"
    store.knowledge_bucket = "knowledge"

    await store.ensure_buckets()

    assert store._client.exists_calls == {"materials": 2, "knowledge": 2}


@pytest.mark.asyncio
async def test_minio_errors_have_structured_service_semantics() -> None:
    class Client:
        def put_object(self, *_: object, **__: object) -> None:
            raise OSError("connection refused")

        def get_object(self, _bucket: str, key: str) -> None:
            raise S3Error(
                None, "NoSuchKey", "not found", key,
                "request", "host", object_name=key,
            )

    store = object.__new__(MinioObjectStore)
    store._client = Client()  # type: ignore[attr-defined]
    with pytest.raises(DependencyUnavailable) as unavailable:
        await store.put_bytes("materials", "key", b"demo", "text/plain")
    assert unavailable.value.status_code == 503
    assert unavailable.value.code == "minio_unavailable"

    with pytest.raises(ConflictError) as missing:
        await store.get_bytes("materials", "missing")
    assert missing.value.status_code == 409
    assert missing.value.code == "material_integrity_failed"


class _SeedDependency:
    def __init__(self) -> None:
        self.pings = 0
        self.seeds = 0

    async def ping(self) -> None:
        self.pings += 1

    async def seed(self, *_: object) -> None:
        self.seeds += 1
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_readiness_seed_retries_are_single_flight_per_dependency() -> None:
    postgres = _SeedDependency()
    milvus = _SeedDependency()
    business_seed = _SeedDependency()

    class Business:
        object_store = _SeedDependency()

        async def startup(self) -> None:
            await business_seed.seed()

    postgres.seed_knowledge = postgres.seed  # type: ignore[attr-defined]
    milvus.ensure_seed = milvus.seed  # type: ignore[attr-defined]
    services = object.__new__(AppServices)
    services.settings = SimpleNamespace(seed_on_startup=True)
    services.database = postgres
    services.milvus = milvus
    services.business = Business()
    services._seed_failures = {"postgres", "milvus", "business"}
    services._seed_retry_lock = asyncio.Lock()
    services._seed_retry_tasks = {}

    probes = (
        [services._postgres_ready() for _ in range(8)]
        + [services._milvus_ready() for _ in range(8)]
        + [services._business_ready() for _ in range(8)]
    )
    await asyncio.gather(*probes)

    assert postgres.seeds == 1
    assert milvus.seeds == 1
    assert business_seed.seeds == 1
    assert services._seed_failures == set()
    assert services._seed_retry_tasks == {}


@pytest.mark.asyncio
async def test_failed_single_flight_stays_retryable_until_later_success() -> None:
    class Postgres(_SeedDependency):
        async def seed_knowledge(self, *_: object) -> None:
            self.seeds += 1
            await asyncio.sleep(0.01)
            if self.seeds == 1:
                raise RuntimeError("transient")

    postgres = Postgres()
    services = object.__new__(AppServices)
    services.settings = SimpleNamespace(seed_on_startup=True)
    services.database = postgres
    services._seed_failures = {"postgres"}

    first = await asyncio.gather(
        *(services._postgres_ready() for _ in range(8)),
        return_exceptions=True,
    )
    assert all(isinstance(result, RuntimeError) for result in first)
    assert postgres.seeds == 1
    assert "postgres" in services._seed_failures

    await asyncio.gather(*(services._postgres_ready() for _ in range(8)))
    assert postgres.seeds == 2
    assert "postgres" not in services._seed_failures


@pytest.mark.asyncio
async def test_database_seed_uses_atomic_postgresql_upsert() -> None:
    statements: list[Any] = []

    class Session:
        async def execute(self, statement: Any) -> None:
            statements.append(statement)

    class Begin:
        async def __aenter__(self) -> Session:
            return Session()

        async def __aexit__(self, *_: object) -> None:
            return None

    class Sessions:
        def begin(self) -> Begin:
            return Begin()

    database = object.__new__(Database)
    database.sessions = Sessions()
    document = {
        "id": "legacy-1",
        "title": "演示事项",
        "content": "演示知识内容",
        "source": "demo://legacy-1",
        "metadata": {"demo": True},
    }

    await database.seed_knowledge([document])

    assert len(statements) == 1
    sql = str(statements[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (id) DO UPDATE" in sql
    assert "content_hash = excluded.content_hash" in sql
    assert "metadata = excluded.metadata" in sql


class _MilvusClient:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.exists = False
        self.creates = 0
        self.upserts = 0
        self.upsert_payloads: list[list[dict[str, object]]] = []
        self.search_filter: str | None = None
        self.deleted_ids: list[str] = []

    def has_collection(self, **_: object) -> bool:
        with self._lock:
            return self.exists

    def create_collection(self, **_: object) -> None:
        with self._lock:
            self.creates += 1
            self.exists = True

    def upsert(self, **values: object) -> None:
        with self._lock:
            self.upserts += 1
            self.upsert_payloads.append(values["data"])  # type: ignore[arg-type]

    def search(self, **values: object) -> list[list[dict[str, object]]]:
        self.search_filter = str(values.get("filter"))
        return [[]]

    def delete(self, **values: object) -> None:
        self.deleted_ids.extend(values["ids"])  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_milvus_collection_initialization_is_process_single_flight() -> None:
    client = _MilvusClient()
    rag = MilvusRAG("http://milvus", "knowledge", 1.0)
    rag._client = client
    document = {
        "id": "legacy-1",
        "title": "演示事项",
        "content": "演示知识内容",
        "source": "demo://legacy-1",
    }
    chunk = {
        "id": "chunk-1",
        "title": "演示事项",
        "content": "演示知识内容",
        "source": "demo://chunk-1",
    }

    await asyncio.gather(
        *(rag.ensure_seed([document]) for _ in range(6)),
        *(rag.index_chunks([chunk]) for _ in range(6)),
    )

    assert client.creates == 1
    assert client.upserts == 12


@pytest.mark.asyncio
async def test_milvus_tolerates_cross_replica_create_already_exists_race() -> None:
    class ExternalRaceClient(_MilvusClient):
        def create_collection(self, **_: object) -> None:
            with self._lock:
                self.creates += 1
                self.exists = True
            raise RuntimeError("collection already exists")

    client = ExternalRaceClient()
    rag = MilvusRAG("http://milvus", "knowledge", 1.0)
    rag._client = client

    await rag.ensure_seed(
        [
            {
                "id": "legacy-1",
                "title": "演示事项",
                "content": "演示知识内容",
                "source": "demo://legacy-1",
            }
        ]
    )

    assert client.creates == 1
    assert client.upserts == 1


@pytest.mark.asyncio
async def test_milvus_only_retrieves_active_knowledge_and_supports_compensation() -> None:
    client = _MilvusClient()
    client.exists = True
    rag = MilvusRAG("http://milvus", "knowledge", 1.0)
    rag._client = client
    chunk = {
        "id": "chunk-1", "title": "演示事项",
        "content": "演示知识内容", "source": "demo://chunk-1",
    }

    await rag.index_chunks([chunk])
    await rag.search("演示")
    await rag.activate_chunks([chunk])
    await rag.delete_chunks(["chunk-1"])

    assert client.upsert_payloads[0][0]["status"] == "INDEXING"
    assert client.upsert_payloads[1][0]["status"] == "ACTIVE"
    assert client.search_filter == 'status == "ACTIVE"'
    assert client.deleted_ids == ["chunk-1"]
