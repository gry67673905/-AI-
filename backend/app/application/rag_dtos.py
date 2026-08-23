from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CorpusChunkData:
    external_id: str
    topic_slug: str
    topic_name: str
    document_title: str
    section: str
    chunk_type: str
    content: str
    source_content_hash: str
    content_hash: str
    theme: str | None = None


@dataclass(frozen=True, slots=True)
class CorpusRouteData:
    topic_slug: str
    topic_name: str
    document_title: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class CorpusArchiveData:
    archive_sha256: str
    chunks: list[CorpusChunkData]
    routes: list[CorpusRouteData]
    topics: dict[str, str]
    sanitized_phone_count: int = 0
    sanitized_email_count: int = 0


@dataclass(frozen=True, slots=True)
class CorpusDatasetSpec:
    name: str
    version: str
    archive_sha256: str
    manifest_hash: str
    expected_chunk_count: int
    embedding_model: str
    embedding_dimension: int
    collection_name: str
    route_collection_name: str
    collection_alias: str
    route_alias: str
    license_status: str = "UNVERIFIED"
    source_owner: str | None = None


@dataclass(frozen=True, slots=True)
class CorpusDatasetState:
    dataset_id: UUID
    status: str
    expected_chunk_count: int
    indexed_chunk_count: int
    reused: bool = False


@dataclass(frozen=True, slots=True)
class CorpusImportResult:
    dataset_id: UUID
    dataset_version: str
    status: str
    chunks: int
    routes: int
    unique_embeddings: int
    reused_embeddings: int
    collection_name: str
    route_collection_name: str
    warnings: list[str] = field(default_factory=list)
