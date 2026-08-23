from __future__ import annotations

import asyncio
from dataclasses import replace

from app.application.dtos import KnowledgeSearchResult, SourceData
from app.application.ports import CorpusSearchPort, KnowledgeRetrievalPort
from app.knowledge import normalize_text


class CompositeKnowledgeRetriever:
    """Fuse internal and group RAG ranks while preserving partial availability."""

    def __init__(
        self,
        primary: KnowledgeRetrievalPort,
        group: CorpusSearchPort | None,
        *,
        limit: int = 6,
        rrf_k: int = 60,
    ) -> None:
        self.primary = primary
        self.group = group
        self.limit = limit
        self.rrf_k = rrf_k

    async def search(self, query: str, limit: int | None = None) -> list[SourceData]:
        result = await self.search_with_warnings(query, limit=limit)
        return result.sources

    async def search_with_warnings(
        self, query: str, limit: int | None = None
    ) -> KnowledgeSearchResult:
        target_limit = limit or self.limit
        calls = [self.primary.search(query, limit=target_limit)]
        labels = ["primary"]
        if self.group is not None:
            calls.append(self.group.search(query, limit=target_limit))
            labels.append("group")
        outcomes = await asyncio.gather(*calls, return_exceptions=True)
        rankings: list[list[SourceData]] = []
        warnings: list[str] = []
        for label, outcome in zip(labels, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                warnings.append(
                    "rag_group_unavailable: 组员知识库暂不可用，已使用本地知识库"
                    if label == "group"
                    else "rag_primary_unavailable: 本地知识库暂不可用，已使用组员知识库"
                )
            else:
                rankings.append(outcome)
        if not rankings:
            raise RuntimeError("all knowledge retrieval backends are unavailable")
        return KnowledgeSearchResult(
            sources=self._rrf(rankings, target_limit),
            warnings=warnings,
        )

    def _rrf(
        self, rankings: list[list[SourceData]], limit: int
    ) -> list[SourceData]:
        fused: dict[str, tuple[SourceData, float, int]] = {}
        order = 0
        for ranking in rankings:
            seen_in_ranking: set[str] = set()
            for rank, source in enumerate(ranking, 1):
                fingerprint = normalize_text(source.excerpt)
                if not fingerprint or fingerprint in seen_in_ranking:
                    continue
                seen_in_ranking.add(fingerprint)
                contribution = 1.0 / (self.rrf_k + rank)
                if fingerprint in fused:
                    current, score, first_order = fused[fingerprint]
                    fused[fingerprint] = (
                        current, score + contribution, first_order
                    )
                else:
                    fused[fingerprint] = (source, contribution, order)
                    order += 1
        ranked = sorted(fused.values(), key=lambda item: (-item[1], item[2]))
        return [
            replace(source, score=score)
            for source, score, _ in ranked[:limit]
        ]
