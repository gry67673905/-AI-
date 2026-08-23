from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.application.rag_dtos import (
    CorpusChunkData,
    CorpusDatasetSpec,
    CorpusRouteData,
)
from app.infrastructure.rag_corpus_milvus import (
    GroupCorpusRetriever,
    VersionedMilvusCorpusIndex,
)
from app.services import AppServices


class Client:
    def __init__(self) -> None:
        self.collections: dict[str, dict[str, dict[str, object]]] = {}
        self.aliases: dict[str, str] = {}
        self.filters: list[str] = []
        self.query_consistency_levels: list[object] = []

    def has_collection(self, collection_name: str) -> bool:
        return collection_name in self.collections

    def create_collection(self, collection_name: str, **_kwargs: object) -> None:
        self.collections[collection_name] = {}

    def upsert(self, collection_name: str, data: list[dict[str, object]]) -> None:
        rows = self.collections[collection_name]
        for item in data:
            rows[str(item["id"])] = item

    def flush(self, collection_name: str) -> None:
        assert collection_name in self.collections

    def get_collection_stats(self, collection_name: str) -> dict[str, int]:
        return {"row_count": len(self.collections[collection_name])}

    def query(
        self, collection_name: str, **values: object
    ) -> list[dict[str, int]]:
        self.query_consistency_levels.append(values.get("consistency_level"))
        if values.get("output_fields") == ["count(*)"]:
            return [{"count(*)": len(self.collections[collection_name])}]
        return []

    def describe_alias(self, alias: str) -> dict[str, str]:
        if alias not in self.aliases:
            raise RuntimeError("missing")
        return {"alias": alias, "collection": self.aliases[alias]}

    def create_alias(self, collection_name: str, alias: str) -> None:
        self.aliases[alias] = collection_name

    def alter_alias(self, collection_name: str, alias: str) -> None:
        self.aliases[alias] = collection_name

    def search(self, collection_name: str, **values: object):
        self.filters.append(str(values.get("filter")))
        if "route" in collection_name:
            return [[{
                "distance": 0.9,
                "entity": {
                    "topic_slug": "t01", "topic_name": "主题一", "doc_title": "标题一"
                },
            }]]
        return [[
            {
                "distance": 0.95,
                "entity": {
                    "external_id": "t01-000-00", "topic_slug": "t01",
                    "topic_name": "主题一", "doc_title": "标题一",
                    "section": "正文", "chunk_type": "正文", "content": "第一条资料",
                    "content_hash": "a" * 64,
                },
            },
            {
                "distance": 0.90,
                "entity": {
                    "external_id": "t01-000-01", "topic_slug": "t01",
                    "topic_name": "主题一", "doc_title": "标题一",
                    "section": "正文", "chunk_type": "正文", "content": "同文档第二块",
                    "content_hash": "b" * 64,
                },
            },
            {
                "distance": 0.85,
                "entity": {
                    "external_id": "t01-001-00", "topic_slug": "t01",
                    "topic_name": "主题一", "doc_title": "标题二",
                    "section": "正文", "chunk_type": "正文", "content": "第二条资料",
                    "content_hash": "c" * 64,
                },
            },
        ]]


class Embedding:
    model_name = "fake"
    dimension = 4

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


def _spec() -> CorpusDatasetSpec:
    return CorpusDatasetSpec(
        name="group-rag", version="v1", archive_sha256="a" * 64,
        manifest_hash="b" * 64, expected_chunk_count=1,
        embedding_model="fake", embedding_dimension=4,
        collection_name="gov_group_rag_v1_aaaaaaaa",
        route_collection_name="gov_group_rag_v1_aaaaaaaa_route",
        collection_alias="gov_group_rag_active",
        route_alias="gov_group_rag_route_active",
    )


@pytest.mark.asyncio
async def test_versioned_index_creates_upserts_counts_and_switches_aliases() -> None:
    client = Client()
    index = VersionedMilvusCorpusIndex("http://unused", 1, 4, client=client)
    spec = _spec()
    chunk = CorpusChunkData(
        "t01-000-00", "t01", "主题一", "标题一", "正文", "正文", "资料",
        "c" * 64, "d" * 64,
    )
    route = CorpusRouteData("t01", "主题一", "标题一", "e" * 64)

    await index.ensure_collections(spec)
    await index.upsert_chunks(spec, [chunk], [[1, 0, 0, 0]])
    await index.upsert_routes(spec, [route], [[1, 0, 0, 0]])
    assert await index.count_chunks(spec) == 1
    assert await index.count_routes(spec) == 1
    assert client.query_consistency_levels == ["Strong", "Strong"]
    await index.activate_aliases(spec)

    assert client.aliases[spec.collection_alias] == spec.collection_name
    assert client.aliases[spec.route_alias] == spec.route_collection_name
    stored = next(iter(client.collections[spec.collection_name].values()))
    assert stored["dataset_version"] == "v1"
    assert stored["demo_data"] is True
    await index.ping_active(
        collection_alias=spec.collection_alias,
        route_alias=spec.route_alias,
        expected_collection=spec.collection_name,
        expected_route_collection=spec.route_collection_name,
        expected_chunk_count=1,
        expected_route_count=1,
    )


@pytest.mark.asyncio
async def test_group_retriever_routes_deduplicates_documents_and_emits_ragdb_uri() -> None:
    client = Client()
    index = VersionedMilvusCorpusIndex("http://unused", 1, 4, client=client)
    retriever = GroupCorpusRetriever(
        index,
        Embedding(),
        dataset_version="v1",
        collection_alias="gov_group_rag_active",
        route_alias="gov_group_rag_route_active",
    )

    sources = await retriever.search("办理材料", limit=6)

    assert len(sources) == 2
    assert sources[0].reference == "ragdb://v1/t01/t01-000-00"
    assert "未核验演示参考" in sources[0].title
    assert all("dataset_version" in item for item in client.filters)


@pytest.mark.asyncio
async def test_group_corpus_readiness_checks_versioned_aliases_without_embedding() -> None:
    class ReadyIndex:
        def __init__(self) -> None:
            self.values: dict[str, object] | None = None

        async def ping_active(self, **values: object) -> None:
            self.values = values

    index = ReadyIndex()
    services = object.__new__(AppServices)
    services.settings = SimpleNamespace(
        rag_archive_sha256="a" * 64,
        rag_group_collection_prefix="gov_group_rag",
        rag_dataset_version="team-v1",
        rag_group_collection_alias="gov_group_rag_active",
        rag_group_route_alias="gov_group_rag_route_active",
        rag_expected_chunk_count=15_858,
        rag_expected_route_count=1_012,
    )
    services.group_index = index

    await services._rag_corpus_ready()

    assert index.values == {
        "collection_alias": "gov_group_rag_active",
        "route_alias": "gov_group_rag_route_active",
        "expected_collection": "gov_group_rag_team_v1_aaaaaaaa",
        "expected_route_collection": "gov_group_rag_team_v1_aaaaaaaa_route",
        "expected_chunk_count": 15_858,
        "expected_route_count": 1_012,
    }
