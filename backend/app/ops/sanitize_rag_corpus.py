from __future__ import annotations

import argparse
import json
import sys

from app.infrastructure.rag_corpus_archive import (
    ReadOnlyRagCorpusArchive,
    write_sanitized_archive,
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Create a data-only RAG ZIP without code, keys or native vectors."
    )
    result.add_argument("--source", required=True)
    result.add_argument("--output", required=True)
    result.add_argument("--expected-source-sha256", required=True)
    result.add_argument("--expected-chunks", type=int, default=15_858)
    return result


def main() -> None:
    args = parser().parse_args()
    try:
        reader = ReadOnlyRagCorpusArchive()
        archive = reader.read(
            args.source,
            expected_sha256=args.expected_source_sha256,
            expected_chunk_count=args.expected_chunks,
        )
        output_sha = write_sanitized_archive(archive, args.output)
        print(
            json.dumps(
                {
                    "status": "SANITIZED",
                    "output_sha256": output_sha,
                    "chunks": len(archive.chunks),
                    "routes": len(archive.routes),
                    "phone_values_removed": archive.sanitized_phone_count,
                    "email_values_removed": archive.sanitized_email_count,
                    "copied_code_files": 0,
                    "copied_vector_files": 0,
                },
                ensure_ascii=False,
            )
        )
    except Exception as exc:
        print(f"RAG sanitization failed ({type(exc).__name__})", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
