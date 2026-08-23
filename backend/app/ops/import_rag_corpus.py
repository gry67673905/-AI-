from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict

from app.application.rag_dtos import CorpusDatasetSpec
from app.application.rag_import import (
    RagCorpusImportCoordinator,
    versioned_collection_names,
)
from app.cache import RetrievalCache
from app.config import get_settings
from app.database import Database
from app.infrastructure.dashscope_embedding import DashScopeEmbeddingAdapter
from app.infrastructure.rag_corpus_archive import ReadOnlyRagCorpusArchive
from app.infrastructure.rag_corpus_milvus import VersionedMilvusCorpusIndex
from app.infrastructure.rag_corpus_repository import SqlAlchemyCorpusRepository


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Inspect or import the allowlisted group RAG JSONL corpus."
    )
    result.add_argument("--zip", required=True, dest="archive_path")
    result.add_argument("--dataset-version", required=True)
    result.add_argument("--dataset-name", default="group-rag")
    result.add_argument("--expected-sha256")
    result.add_argument("--expected-chunks", type=int, default=15_858)
    result.add_argument("--source-owner", default="project-team")
    result.add_argument(
        "--license-status",
        choices=("UNVERIFIED", "INTERNAL_APPROVED", "APPROVED"),
        default="UNVERIFIED",
    )
    result.add_argument("--allow-unverified-demo", action="store_true")
    result.add_argument("--dry-run", action="store_true")
    return result


async def run(args: argparse.Namespace) -> int:
    reader = ReadOnlyRagCorpusArchive()
    archive = await asyncio.to_thread(
        reader.read,
        args.archive_path,
        expected_sha256=args.expected_sha256,
        expected_chunk_count=args.expected_chunks,
    )
    manifest_hash = reader.manifest_hash(archive)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "VALID",
                    "archive_sha256": archive.archive_sha256,
                    "manifest_hash": manifest_hash,
                    "chunks": len(archive.chunks),
                    "routes": len(archive.routes),
                    "topics": len(archive.topics),
                    "sanitized_phone_count": archive.sanitized_phone_count,
                    "sanitized_email_count": archive.sanitized_email_count,
                    "network_calls": 0,
                    "writes": 0,
                },
                ensure_ascii=False,
            )
        )
        return 0
    if not args.expected_sha256:
        raise SystemExit("--expected-sha256 is required for a state-changing import")
    if args.license_status != "APPROVED" and not args.allow_unverified_demo:
        raise SystemExit(
            "unverified corpus activation requires --allow-unverified-demo"
        )

    settings = get_settings()
    collection_name, route_collection_name = versioned_collection_names(
        settings.rag_group_collection_prefix,
        args.dataset_version,
        archive.archive_sha256,
    )
    spec = CorpusDatasetSpec(
        name=args.dataset_name,
        version=args.dataset_version,
        archive_sha256=archive.archive_sha256,
        manifest_hash=manifest_hash,
        expected_chunk_count=args.expected_chunks,
        embedding_model=settings.dashscope_embedding_model,
        embedding_dimension=settings.dashscope_embedding_dimension,
        collection_name=collection_name,
        route_collection_name=route_collection_name,
        collection_alias=settings.rag_group_collection_alias,
        route_alias=settings.rag_group_route_alias,
        license_status=args.license_status,
        source_owner=args.source_owner,
    )
    database = Database(settings.database_url)
    cache = RetrievalCache(
        settings.redis_url,
        settings.cache_ttl_seconds,
        dataset_version=args.dataset_version,
    )
    embedding = DashScopeEmbeddingAdapter(
        api_key=settings.dashscope_api_key,
        api_key_file=settings.dashscope_api_key_file,
        model_name=settings.dashscope_embedding_model,
        dimension=settings.dashscope_embedding_dimension,
        base_url=settings.dashscope_embedding_base_url,
        timeout_seconds=settings.dashscope_embedding_timeout_seconds,
        max_retries=settings.dashscope_embedding_max_retries,
    )
    index = VersionedMilvusCorpusIndex(
        settings.milvus_uri,
        settings.milvus_timeout_seconds,
        settings.dashscope_embedding_dimension,
    )
    coordinator = RagCorpusImportCoordinator(
        reader,
        SqlAlchemyCorpusRepository(database.sessions),
        embedding,
        index,
        cache=cache,
        batch_size=settings.rag_import_batch_size,
        batch_retries=settings.rag_import_batch_retries,
    )
    try:
        result = await coordinator.run(archive, spec)
        print(json.dumps(asdict(result), ensure_ascii=False, default=str))
    finally:
        await asyncio.gather(
            embedding.close(), cache.close(), database.dispose(),
            return_exceptions=True,
        )
    return 0


def main() -> None:
    try:
        raise SystemExit(asyncio.run(run(parser().parse_args())))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception as exc:
        # Never render provider response bodies, SQL text, local secret values,
        # or archive content in operational failures.
        print(
            f"RAG import failed ({type(exc).__name__})",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
