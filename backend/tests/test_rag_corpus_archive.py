from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from app.infrastructure.rag_corpus_archive import (
    CorpusArchiveValidationError,
    ReadOnlyRagCorpusArchive,
    write_sanitized_archive,
)


def _archive(path: Path, *, unsafe: bool = False) -> None:
    topics = [
        {"slug": f"t{index:02d}", "name": f"主题{index}"}
        for index in range(1, 30)
    ]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("RAG_DATABASE/topics.json", json.dumps(topics, ensure_ascii=False))
        for index in range(1, 30):
            slug = f"t{index:02d}"
            rows: list[dict[str, str]] = []
            if index == 1:
                rows = [
                    {
                        "id": "t01-000-00",
                        "doc": "联系13800138000",
                        "section": "常规信息",
                        "chunk_type": "正文",
                        "text": "邮箱demo@example.com，电话13800138000",
                    },
                    {
                        "id": "faq-t01-001",
                        "doc": "办理问题",
                        "section": "常见问题",
                        "chunk_type": "问答",
                        "text": "问：怎么办？答：演示办理。",
                        "theme": "主题1",
                    },
                ]
            archive.writestr(
                f"RAG_DATABASE/chunks/{slug}.jsonl",
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            )
        # These entries must never be parsed or extracted.
        archive.writestr("RAG_DATABASE/config.py", "API_KEY='do-not-read'")
        archive.writestr("RAG_DATABASE/vectors/t01/manifest.3", b"native-index")
        if unsafe:
            archive.writestr("../escape.txt", "blocked")


def test_archive_reads_only_allowlisted_jsonl_and_sanitizes_contacts(tmp_path: Path) -> None:
    path = tmp_path / "rag.zip"
    _archive(path)
    reader = ReadOnlyRagCorpusArchive()

    result = reader.read(str(path), expected_chunk_count=2)

    assert len(result.chunks) == 2
    assert len(result.routes) == 2
    assert result.sanitized_phone_count == 2
    assert result.sanitized_email_count == 1
    assert "13800138000" not in result.chunks[0].document_title
    assert "13800138000" not in result.chunks[0].content
    assert "demo@example.com" not in result.chunks[0].content
    assert result.chunks[0].source_content_hash != result.chunks[0].content_hash
    assert len(reader.manifest_hash(result)) == 64


def test_archive_rejects_unsafe_member_even_when_not_allowlisted(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.zip"
    _archive(path, unsafe=True)

    with pytest.raises(CorpusArchiveValidationError, match="不安全路径"):
        ReadOnlyRagCorpusArchive().read(str(path), expected_chunk_count=2)


def test_sanitized_archive_contains_only_data_allowlist_and_preserves_source_hash(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.zip"
    output = tmp_path / "sanitized.zip"
    _archive(source)
    reader = ReadOnlyRagCorpusArchive()
    original = reader.read(str(source), expected_chunk_count=2)

    output_sha = write_sanitized_archive(original, str(output))
    sanitized = reader.read(
        str(output), expected_sha256=output_sha, expected_chunk_count=2
    )
    with zipfile.ZipFile(output) as emitted:
        names = set(emitted.namelist())

    assert "RAG_DATABASE/config.py" not in names
    assert not any(name.startswith("RAG_DATABASE/vectors/") for name in names)
    assert names == {
        "RAG_DATABASE/topics.json",
        "RAG_DATABASE/manifest.json",
        *(f"RAG_DATABASE/chunks/t{index:02d}.jsonl" for index in range(1, 30)),
    }
    assert sanitized.sanitized_phone_count == 0
    assert sanitized.sanitized_email_count == 0
    assert sanitized.chunks[0].source_content_hash == original.chunks[0].source_content_hash


def test_delivered_archive_has_expected_sanitized_manifest() -> None:
    path = Path(__file__).resolve().parents[3] / "RAG_DATABASE .zip"
    if not path.is_file():
        pytest.skip("delivered group RAG archive is not present")
    result = ReadOnlyRagCorpusArchive().read(
        str(path),
        expected_sha256=(
            "930D57D7326192B57F6744D168ADC3D50C920D42896862C6395413E98D09CEDD"
        ),
        expected_chunk_count=15_858,
    )

    assert len(result.chunks) == 15_858
    assert len(result.routes) == 1_012
    assert len(result.topics) == 29
    assert result.sanitized_phone_count == 17
    assert result.sanitized_email_count == 62
