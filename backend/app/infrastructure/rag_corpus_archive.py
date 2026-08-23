from __future__ import annotations

import hashlib
import hmac
import io
import json
import shutil
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from app.application.rag_dtos import (
    CorpusArchiveData,
    CorpusChunkData,
    CorpusRouteData,
)


_TOPICS_ENTRY = "RAG_DATABASE/topics.json"
_CHUNK_ENTRY_RE = re.compile(r"^RAG_DATABASE/chunks/(t\d{2})\.jsonl$")
_TOPIC_RE = re.compile(r"^t\d{2}$")
_ASCII_ID_RE = re.compile(r"^[\x21-\x7e]{1,64}$")
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@"
    r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])"
)
_CHINA_ID_RE = re.compile(
    r"(?<!\d)[1-9]\d{5}(?:18|19|20)\d{2}"
    r"(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx](?!\d)"
)
_ALLOWED_CHUNK_FIELDS = {
    "id", "doc", "section", "chunk_type", "text", "theme",
    "source_content_hash",
}


class CorpusArchiveValidationError(ValueError):
    pass


def sanitize_corpus_text(value: str) -> tuple[str, int, int]:
    """Remove contact/identity strings before persistence, embedding or upload."""

    sanitized, email_count = _EMAIL_RE.subn("[已脱敏邮箱]", value)
    sanitized, phone_count = _PHONE_RE.subn("[已脱敏手机号]", sanitized)
    sanitized = _CHINA_ID_RE.sub("[已脱敏身份证号]", sanitized)
    return sanitized, phone_count, email_count


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_entry_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:", normalized)
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise CorpusArchiveValidationError("压缩包包含不安全路径")
    return path.as_posix()


class ReadOnlyRagCorpusArchive:
    """Read only the topics/JSONL allowlist; never extract or import executable files."""

    max_archive_bytes = 100 * 1024 * 1024
    max_uncompressed_bytes = 600 * 1024 * 1024
    max_entry_bytes = 20 * 1024 * 1024
    max_content_chars = 20_000

    def read(
        self,
        archive_path: str,
        *,
        expected_sha256: str | None = None,
        expected_chunk_count: int = 15_858,
    ) -> CorpusArchiveData:
        path = Path(archive_path)
        if not path.is_file():
            raise CorpusArchiveValidationError("RAG 压缩包不存在")
        if path.stat().st_size > self.max_archive_bytes:
            raise CorpusArchiveValidationError("RAG 压缩包超过安全大小限制")

        archive_hash = self._file_sha256(path)
        if expected_sha256 and not hmac.compare_digest(
            archive_hash.lower(), expected_sha256.strip().lower()
        ):
            raise CorpusArchiveValidationError("RAG 压缩包 SHA-256 不匹配")

        with zipfile.ZipFile(path, "r") as archive:
            entries = self._validated_entries(archive)
            topics = self._read_topics(archive, entries)
            chunks, phone_count, email_count = self._read_chunks(
                archive, entries, topics
            )

        if len(chunks) != expected_chunk_count:
            raise CorpusArchiveValidationError(
                f"RAG 分块数量不匹配：expected={expected_chunk_count}, actual={len(chunks)}"
            )

        routes_by_key: dict[tuple[str, str], CorpusRouteData] = {}
        for chunk in chunks:
            key = (chunk.topic_slug, chunk.document_title)
            routes_by_key.setdefault(
                key,
                CorpusRouteData(
                    topic_slug=chunk.topic_slug,
                    topic_name=chunk.topic_name,
                    document_title=chunk.document_title,
                    content_hash=_sha256_text(chunk.document_title),
                ),
            )

        manifest = hashlib.sha256()
        for chunk in sorted(chunks, key=lambda item: item.external_id):
            manifest.update(
                (
                    f"{chunk.topic_slug}\0{chunk.external_id}\0"
                    f"{chunk.source_content_hash}\0{chunk.content_hash}\n"
                ).encode("utf-8")
            )
        return CorpusArchiveData(
            archive_sha256=archive_hash,
            chunks=chunks,
            routes=sorted(
                routes_by_key.values(),
                key=lambda item: (item.topic_slug, item.document_title),
            ),
            topics=topics,
            sanitized_phone_count=phone_count,
            sanitized_email_count=email_count,
        )

    @staticmethod
    def manifest_hash(archive: CorpusArchiveData) -> str:
        digest = hashlib.sha256()
        for chunk in sorted(archive.chunks, key=lambda item: item.external_id):
            digest.update(
                (
                    f"{chunk.topic_slug}\0{chunk.external_id}\0"
                    f"{chunk.source_content_hash}\0{chunk.content_hash}\n"
                ).encode("utf-8")
            )
        return digest.hexdigest()

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _validated_entries(
        self, archive: zipfile.ZipFile
    ) -> dict[str, zipfile.ZipInfo]:
        entries: dict[str, zipfile.ZipInfo] = {}
        total_size = 0
        for info in archive.infolist():
            name = _safe_entry_name(info.filename)
            if name in entries:
                raise CorpusArchiveValidationError("RAG 压缩包包含重复条目")
            entries[name] = info
            total_size += info.file_size
            if info.file_size > self.max_entry_bytes:
                # Large native vector files are intentionally ignored, but still
                # bounded to prevent a disguised archive bomb.
                if not name.startswith("RAG_DATABASE/vectors/"):
                    raise CorpusArchiveValidationError("RAG 压缩包条目超过安全限制")
        if total_size > self.max_uncompressed_bytes:
            raise CorpusArchiveValidationError("RAG 压缩包解压体积超过安全限制")
        return entries

    @staticmethod
    def _read_json_entry(
        archive: zipfile.ZipFile,
        info: zipfile.ZipInfo,
    ) -> Any:
        with archive.open(info, "r") as raw:
            with io.TextIOWrapper(raw, encoding="utf-8-sig", errors="strict") as text:
                return json.load(text)

    def _read_topics(
        self,
        archive: zipfile.ZipFile,
        entries: dict[str, zipfile.ZipInfo],
    ) -> dict[str, str]:
        info = entries.get(_TOPICS_ENTRY)
        if info is None:
            raise CorpusArchiveValidationError("RAG 压缩包缺少 topics.json")
        payload = self._read_json_entry(archive, info)
        if not isinstance(payload, list):
            raise CorpusArchiveValidationError("topics.json 格式无效")
        topics: dict[str, str] = {}
        for item in payload:
            if not isinstance(item, dict):
                raise CorpusArchiveValidationError("topics.json 条目无效")
            slug = str(item.get("slug", ""))
            name = str(item.get("name", "")).strip()
            if not _TOPIC_RE.fullmatch(slug) or not name or len(name) > 100:
                raise CorpusArchiveValidationError("topics.json 主题字段无效")
            if slug in topics:
                raise CorpusArchiveValidationError("topics.json 包含重复主题")
            topics[slug] = name
        if len(topics) != 29:
            raise CorpusArchiveValidationError("RAG 主题数量必须为 29")
        return topics

    def _read_chunks(
        self,
        archive: zipfile.ZipFile,
        entries: dict[str, zipfile.ZipInfo],
        topics: dict[str, str],
    ) -> tuple[list[CorpusChunkData], int, int]:
        chunk_entries: dict[str, zipfile.ZipInfo] = {}
        for name, info in entries.items():
            matched = _CHUNK_ENTRY_RE.fullmatch(name)
            if matched:
                chunk_entries[matched.group(1)] = info
        if set(chunk_entries) != set(topics):
            raise CorpusArchiveValidationError("RAG 分块文件与 29 个主题不一致")

        chunks: list[CorpusChunkData] = []
        seen_ids: set[str] = set()
        phone_count = email_count = 0
        for slug in sorted(chunk_entries):
            info = chunk_entries[slug]
            with archive.open(info, "r") as raw:
                with io.TextIOWrapper(
                    raw, encoding="utf-8-sig", errors="strict", newline=""
                ) as text:
                    for line_number, line in enumerate(text, 1):
                        if not line.strip():
                            continue
                        try:
                            payload = json.loads(line)
                        except json.JSONDecodeError as exc:
                            raise CorpusArchiveValidationError(
                                f"RAG JSONL 格式无效：{slug}:{line_number}"
                            ) from exc
                        chunk = self._chunk(payload, slug, topics[slug])
                        if chunk.external_id in seen_ids:
                            raise CorpusArchiveValidationError("RAG external_id 重复")
                        seen_ids.add(chunk.external_id)
                        chunks.append(chunk)
                        _, phones, emails = self._sanitized_values(payload)
                        phone_count += phones
                        email_count += emails
        return chunks, phone_count, email_count

    def _chunk(
        self, payload: Any, topic_slug: str, topic_name: str
    ) -> CorpusChunkData:
        if not isinstance(payload, dict) or not set(payload).issubset(
            _ALLOWED_CHUNK_FIELDS
        ):
            raise CorpusArchiveValidationError("RAG 分块字段不在白名单内")
        for required in ("id", "doc", "section", "chunk_type", "text"):
            if not isinstance(payload.get(required), str):
                raise CorpusArchiveValidationError("RAG 分块缺少必需字符串字段")
        external_id = payload["id"].strip()
        if not _ASCII_ID_RE.fullmatch(external_id):
            raise CorpusArchiveValidationError("RAG external_id 必须为安全 ASCII")
        sanitized, _, _ = self._sanitized_values(payload)
        title, content = sanitized
        section = payload["section"].strip()
        chunk_type = payload["chunk_type"].strip()
        theme = payload.get("theme")
        if theme is not None:
            if not isinstance(theme, str) or len(theme.strip()) > 100:
                raise CorpusArchiveValidationError("RAG FAQ theme 无效")
            theme = theme.strip() or None
        if not title or len(title) > 500:
            raise CorpusArchiveValidationError("RAG 文档标题无效")
        if not section or len(section) > 100:
            raise CorpusArchiveValidationError("RAG section 无效")
        if chunk_type not in {"摘要", "正文", "问答"}:
            raise CorpusArchiveValidationError("RAG chunk_type 无效")
        if not content or len(content) > self.max_content_chars:
            raise CorpusArchiveValidationError("RAG 分块正文为空或过长")
        raw_content = payload["text"]
        supplied_source_hash = payload.get("source_content_hash")
        if supplied_source_hash is not None and (
            not isinstance(supplied_source_hash, str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", supplied_source_hash)
        ):
            raise CorpusArchiveValidationError("RAG source_content_hash 无效")
        return CorpusChunkData(
            external_id=external_id,
            topic_slug=topic_slug,
            topic_name=topic_name,
            document_title=title,
            section=section,
            chunk_type=chunk_type,
            content=content,
            source_content_hash=(
                supplied_source_hash.lower()
                if isinstance(supplied_source_hash, str)
                else _sha256_text(raw_content)
            ),
            content_hash=_sha256_text(content),
            theme=theme,
        )

    @staticmethod
    def _sanitized_values(payload: dict[str, Any]) -> tuple[tuple[str, str], int, int]:
        title, title_phones, title_emails = sanitize_corpus_text(payload["doc"].strip())
        content, content_phones, content_emails = sanitize_corpus_text(payload["text"])
        return (
            (title, content),
            title_phones + content_phones,
            title_emails + content_emails,
        )


def write_sanitized_archive(
    archive: CorpusArchiveData,
    output_path: str,
) -> str:
    """Create a deterministic data-only ZIP; never copy code, keys or vectors."""

    output = Path(output_path)
    if output.exists():
        raise CorpusArchiveValidationError("净化输出文件已存在，拒绝覆盖")
    if not output.parent.is_dir():
        raise CorpusArchiveValidationError("净化输出目录不存在")
    temporary = output.with_name(output.name + ".tmp")
    if temporary.exists():
        raise CorpusArchiveValidationError("净化临时文件已存在")

    def info(name: str) -> zipfile.ZipInfo:
        item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        item.compress_type = zipfile.ZIP_DEFLATED
        item.external_attr = 0o600 << 16
        return item

    grouped: dict[str, list[CorpusChunkData]] = {
        slug: [] for slug in archive.topics
    }
    for chunk in archive.chunks:
        grouped[chunk.topic_slug].append(chunk)
    manifest_hash = ReadOnlyRagCorpusArchive.manifest_hash(archive)
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as target:
            topics_payload = [
                {"slug": slug, "name": archive.topics[slug]}
                for slug in sorted(archive.topics)
            ]
            target.writestr(
                info(_TOPICS_ENTRY),
                json.dumps(
                    topics_payload, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8"),
            )
            for slug in sorted(grouped):
                lines: list[str] = []
                for chunk in grouped[slug]:
                    row: dict[str, Any] = {
                        "id": chunk.external_id,
                        "doc": chunk.document_title,
                        "section": chunk.section,
                        "chunk_type": chunk.chunk_type,
                        "text": chunk.content,
                        "source_content_hash": chunk.source_content_hash,
                    }
                    if chunk.theme:
                        row["theme"] = chunk.theme
                    lines.append(
                        json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                    )
                payload = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
                target.writestr(
                    info(f"RAG_DATABASE/chunks/{slug}.jsonl"), payload
                )
            target.writestr(
                info("RAG_DATABASE/manifest.json"),
                json.dumps(
                    {
                        "format": "smart-gov-sanitized-rag-v1",
                        "source_archive_sha256": archive.archive_sha256,
                        "source_manifest_hash": manifest_hash,
                        "chunks": len(archive.chunks),
                        "routes": len(archive.routes),
                        "topics": len(archive.topics),
                        "phone_values_removed": archive.sanitized_phone_count,
                        "email_values_removed": archive.sanitized_email_count,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8"),
            )
        try:
            with temporary.open("rb") as source, output.open("xb") as destination:
                shutil.copyfileobj(source, destination, length=1024 * 1024)
        except Exception:
            output.unlink(missing_ok=True)
            raise
        temporary.unlink()
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    # Validate the emitted data-only artifact before it is eligible for upload.
    validated = ReadOnlyRagCorpusArchive().read(
        str(output), expected_chunk_count=len(archive.chunks)
    )
    if validated.sanitized_phone_count or validated.sanitized_email_count:
        output.unlink(missing_ok=True)
        raise CorpusArchiveValidationError("净化输出仍包含手机号或邮箱")
    return ReadOnlyRagCorpusArchive._file_sha256(output)
