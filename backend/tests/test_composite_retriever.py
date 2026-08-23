from __future__ import annotations

import pytest

from app.application.dtos import SourceData
from app.infrastructure.composite_retriever import CompositeKnowledgeRetriever


class Retriever:
    def __init__(self, sources: list[SourceData] | None = None, fail: bool = False):
        self.sources = sources or []
        self.fail = fail

    async def search(self, _query: str, limit: int = 6) -> list[SourceData]:
        if self.fail:
            raise RuntimeError("unavailable")
        return self.sources[:limit]


@pytest.mark.asyncio
async def test_composite_retriever_rrf_deduplicates_and_preserves_ragdb_reference() -> None:
    duplicate_primary = SourceData(
        kind="rag", title="本地", reference="demo://one", excerpt="相同资料"
    )
    duplicate_group = SourceData(
        kind="rag", title="组员", reference="ragdb://v1/t01/x", excerpt="相同资料"
    )
    group_only = SourceData(
        kind="rag", title="组员二", reference="ragdb://v1/t02/y", excerpt="补充资料"
    )
    retriever = CompositeKnowledgeRetriever(
        Retriever([duplicate_primary]),
        Retriever([duplicate_group, group_only]),  # type: ignore[arg-type]
    )

    result = await retriever.search_with_warnings("怎么办")

    assert len(result.sources) == 2
    assert result.sources[0].reference == "demo://one"
    assert result.sources[0].score == pytest.approx(2 / 61)
    assert result.sources[1].reference.startswith("ragdb://")
    assert result.warnings == []


@pytest.mark.asyncio
async def test_composite_retriever_degrades_with_explicit_warning() -> None:
    source = SourceData(
        kind="rag", title="本地", reference="demo://one", excerpt="本地资料"
    )
    retriever = CompositeKnowledgeRetriever(
        Retriever([source]), Retriever(fail=True)  # type: ignore[arg-type]
    )

    result = await retriever.search_with_warnings("怎么办")

    assert result.sources
    assert result.warnings[0].startswith("rag_group_unavailable:")
