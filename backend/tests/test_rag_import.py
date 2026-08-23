from __future__ import annotations

import hashlib
from uuid import UUID

import pytest

from app.application.rag_dtos import (
    CorpusArchiveData,
    CorpusChunkData,
    CorpusDatasetSpec,
    CorpusDatasetState,
    CorpusRouteData,
)
from app.application.rag_import import (
    RagCorpusImportCoordinator,
    versioned_collection_names,
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _chunk(external_id: str, content: str, title: str) -> CorpusChunkData:
    return CorpusChunkData(
        external_id=external_id,
        topic_slug="t01",
        topic_name="主题一",
        document_title=title,
        section="申请材料",
        chunk_type="正文",
        content=content,
        source_content_hash=_hash(content),
        content_hash=_hash(content),
    )


class Repository:
    dataset_id = UUID("11111111-1111-1111-1111-111111111111")

    def __init__(self, chunks: list[CorpusChunkData]):
        self.pending = list(chunks)
        self.cache: dict[str, list[float]] = {}
        self.active = False
        self.failed: str | None = None

    async def ensure_dataset(self, spec, archive):  # noqa: ANN001
        return CorpusDatasetState(
            self.dataset_id, "INDEXING", spec.expected_chunk_count, 0
        )

    async def pending_chunks(self, _dataset_id, limit):  # noqa: ANN001
        return self.pending[:limit]

    async def cached_embeddings(self, hashes, _model, _dimension):  # noqa: ANN001
        return {item: self.cache[item] for item in hashes if item in self.cache}

    async def store_embeddings(self, embeddings, _model, _dimension):  # noqa: ANN001
        self.cache.update(embeddings)

    async def mark_chunks_indexed(self, _dataset_id, external_ids):  # noqa: ANN001
        selected = set(external_ids)
        self.pending = [item for item in self.pending if item.external_id not in selected]

    async def mark_dataset_active(self, _dataset_id, _count):  # noqa: ANN001
        self.active = True

    async def mark_dataset_failed(self, _dataset_id, error_code):  # noqa: ANN001
        self.failed = error_code


class FakeEmbedding:
    model_name = "fake-1024"
    dimension = 4

    def __init__(self):
        self.texts: list[str] = []

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return [[float(len(text)), 0.0, 0.0, 1.0] for text in texts]


class Index:
    def __init__(
        self, count: int, route_count_after_upsert: int | None = None
    ):
        self.count = count
        self.route_count = 0
        self.route_count_after_upsert = route_count_after_upsert
        self.chunk_attempts = 0
        self.chunk_ids: list[str] = []
        self.route_titles: list[str] = []
        self.activated = False

    async def ensure_collections(self, _spec):  # noqa: ANN001
        return None

    async def upsert_chunks(self, _spec, chunks, _vectors):  # noqa: ANN001
        self.chunk_attempts += 1
        if self.chunk_attempts == 1:
            raise RuntimeError("transient")
        self.chunk_ids.extend(item.external_id for item in chunks)

    async def upsert_routes(self, _spec, routes, _vectors):  # noqa: ANN001
        self.route_titles.extend(item.document_title for item in routes)
        self.route_count = (
            self.route_count_after_upsert
            if self.route_count_after_upsert is not None
            else len(set(self.route_titles))
        )

    async def count_chunks(self, _spec):  # noqa: ANN001
        return self.count

    async def count_routes(self, _spec):  # noqa: ANN001
        return self.route_count

    async def activate_aliases(self, _spec):  # noqa: ANN001
        self.activated = True


class Cache:
    def __init__(self):
        self.invalidations = 0

    async def invalidate_public(self) -> None:
        self.invalidations += 1


def _fixture() -> tuple[CorpusArchiveData, CorpusDatasetSpec]:
    sha = "a" * 64
    chunks = [
        _chunk("t01-000-00", "重复正文", "标题一"),
        _chunk("t01-001-00", "重复正文", "标题二"),
        _chunk("t01-002-00", "唯一正文", "标题三"),
    ]
    routes = [
        CorpusRouteData("t01", "主题一", "标题一", _hash("标题一")),
        CorpusRouteData("t01", "主题一", "标题二", _hash("标题二")),
    ]
    archive = CorpusArchiveData(sha, chunks, routes, {"t01": "主题一"}, 1, 1)
    collection, route_collection = versioned_collection_names("gov_group_rag", "v1", sha)
    spec = CorpusDatasetSpec(
        name="group-rag",
        version="v1",
        archive_sha256=sha,
        manifest_hash="b" * 64,
        expected_chunk_count=3,
        embedding_model="fake-1024",
        embedding_dimension=4,
        collection_name=collection,
        route_collection_name=route_collection,
        collection_alias="gov_group_rag_active",
        route_alias="gov_group_rag_route_active",
    )
    return archive, spec


@pytest.mark.asyncio
async def test_import_reuses_content_embedding_retries_batch_and_activates() -> None:
    archive, spec = _fixture()
    repository = Repository(archive.chunks)
    embedding = FakeEmbedding()
    index = Index(count=3)
    cache = Cache()
    coordinator = RagCorpusImportCoordinator(
        object(),  # type: ignore[arg-type]
        repository,  # type: ignore[arg-type]
        embedding,
        index,  # type: ignore[arg-type]
        cache=cache,  # type: ignore[arg-type]
        batch_size=3,
        batch_retries=1,
    )

    result = await coordinator.run(archive, spec)

    assert result.status == "ACTIVE"
    assert index.chunk_attempts == 2
    assert index.activated is True
    assert repository.active is True
    assert repository.failed is None
    assert cache.invalidations == 1
    assert embedding.texts.count("重复正文") == 1
    assert result.unique_embeddings == 4  # 2 unique chunks + 2 route titles
    assert result.warnings


@pytest.mark.asyncio
async def test_import_count_mismatch_marks_dataset_failed_without_alias_switch() -> None:
    archive, spec = _fixture()
    repository = Repository(archive.chunks)
    index = Index(count=2)
    coordinator = RagCorpusImportCoordinator(
        object(),  # type: ignore[arg-type]
        repository,  # type: ignore[arg-type]
        FakeEmbedding(),
        index,  # type: ignore[arg-type]
        batch_size=3,
        batch_retries=1,
    )

    with pytest.raises(RuntimeError, match="row count"):
        await coordinator.run(archive, spec)

    assert repository.failed == "RuntimeError"
    assert index.activated is False


@pytest.mark.asyncio
async def test_import_route_count_mismatch_prevents_alias_switch() -> None:
    archive, spec = _fixture()
    repository = Repository(archive.chunks)
    index = Index(count=3, route_count_after_upsert=0)
    coordinator = RagCorpusImportCoordinator(
        object(),  # type: ignore[arg-type]
        repository,  # type: ignore[arg-type]
        FakeEmbedding(),
        index,  # type: ignore[arg-type]
        batch_size=3,
        batch_retries=1,
    )

    with pytest.raises(RuntimeError, match="route row count"):
        await coordinator.run(archive, spec)

    assert repository.failed == "RuntimeError"
    assert index.activated is False


def test_versioned_collection_names_reject_untrusted_identifiers() -> None:
    with pytest.raises(ValueError):
        versioned_collection_names("../bad", "v1", "a" * 64)
    with pytest.raises(ValueError):
        versioned_collection_names("gov_group_rag", "v1;drop", "a" * 64)
