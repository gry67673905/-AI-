from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from uuid import UUID, uuid4

from app.application.dtos import Principal
from app.application.ports import ObjectStorePort
from app.domain.enums import (
    MaterialDocumentScope,
    MaterialDocumentStatus,
    MaterialTemplateMode,
    Role,
)
from app.errors import BusinessValidationError, ConflictError, GoneError, PermissionDenied


DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
MAX_GENERATED_DOCUMENT_BYTES = 10 * 1024 * 1024


class MaterialDocumentProcessingError(RuntimeError):
    """Application-visible base for failures carrying a persistence-safe code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class TemplateAnalysis:
    fields: dict[str, str]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LeasedMaterialDocumentJob:
    id: UUID
    owner_account_id: UUID
    application_id: UUID | None
    requirement_code: str
    template_id: UUID
    template_key: str
    template_title: str
    template_mode: MaterialTemplateMode
    allowed_fields: tuple[str, ...]
    source_object_key: str | None
    source_sha256: str | None
    form_snapshot: dict[str, Any]
    request_text: str | None
    lease_token: UUID
    model_name: str = "mock-material-template-v1"
    scope: MaterialDocumentScope = MaterialDocumentScope.APPLICATION
    consultation_session_id: UUID | None = None


class MaterialDocumentRepositoryPort(Protocol):
    async def list_material_template_options(
        self, application_id: UUID, owner_account_id: UUID
    ) -> list[dict[str, Any]]: ...

    async def list_consultation_material_template_options(
        self, service_id: UUID | None = None, query: str | None = None
    ) -> list[dict[str, Any]]: ...

    async def search_consultation_material_template_options(
        self, query: str
    ) -> list[dict[str, Any]]: ...

    async def create_consultation_material_intent(
        self,
        owner_account_id: UUID,
        session_id: UUID,
        service_id: UUID,
        requirement_code: str,
        template_id: UUID,
        request_text: str | None,
        expires_at: datetime,
    ) -> dict[str, Any]: ...

    async def get_consultation_material_intent_states(
        self,
        owner_account_id: UUID,
        session_id: UUID,
        intent_ids: tuple[UUID, ...],
        now: datetime,
    ) -> dict[UUID, dict[str, Any]]: ...

    async def get_latest_pending_consultation_material_intent(
        self, owner_account_id: UUID, session_id: UUID, now: datetime
    ) -> dict[str, Any] | None: ...

    async def confirm_consultation_material_intent(
        self,
        owner_account_id: UUID,
        session_id: UUID,
        intent_id: UUID,
        job_expires_at: datetime,
        model_name: str,
        release_lane: str,
        user_daily_limit: int,
        user_active_limit: int,
        global_daily_limit: int,
        global_queue_limit: int,
    ) -> dict[str, Any]: ...

    async def create_material_document_job(
        self,
        owner_account_id: UUID,
        application_id: UUID,
        requirement_code: str,
        template_id: UUID,
        request_text: str | None,
        expires_at: datetime,
        model_name: str,
        release_lane: str,
        user_daily_limit: int,
        user_active_limit: int,
        global_daily_limit: int,
        global_queue_limit: int,
    ) -> dict[str, Any]: ...

    async def get_material_document_job_authorized(
        self, generation_id: UUID, owner_account_id: UUID
    ) -> dict[str, Any]: ...

    async def lease_material_document_job(
        self, lease_seconds: int, release_lane: str
    ) -> LeasedMaterialDocumentJob | None: ...

    async def renew_material_document_job_lease(
        self, generation_id: UUID, lease_token: UUID, lease_seconds: int
    ) -> bool: ...

    async def complete_material_document_job(
        self,
        generation_id: UUID,
        lease_token: UUID,
        object_key: str,
        filename: str,
        size_bytes: int,
        sha256: str,
        model_name: str,
        warnings: tuple[str, ...],
    ) -> bool: ...

    async def fail_material_document_job(
        self, generation_id: UUID, lease_token: UUID, error_code: str
    ) -> bool: ...

    async def expire_material_document_jobs(
        self, now: datetime
    ) -> list[str]: ...


class MaterialTemplateAnalyzerPort(Protocol):
    model_name: str

    async def analyze(
        self,
        *,
        page_images: tuple[bytes, ...],
        template_title: str,
        allowed_fields: tuple[str, ...],
        form_snapshot: dict[str, Any],
        request_text: str | None,
    ) -> TemplateAnalysis: ...

    async def close(self) -> None: ...


class TemplatePageRendererPort(Protocol):
    async def render_pages(self, source_docx: bytes) -> tuple[bytes, ...]: ...


class DocxMaterialRendererPort(Protocol):
    async def render(
        self,
        *,
        mode: MaterialTemplateMode,
        template_key: str,
        template_title: str,
        source_docx: bytes,
        analysis: TemplateAnalysis,
    ) -> bytes: ...


class MaterialDocumentCoordinator:
    def __init__(
        self,
        repository: MaterialDocumentRepositoryPort,
        object_store: ObjectStorePort,
        idempotency: Any,
        *,
        enabled: bool,
        retention_hours: int,
        model_name: str = "mock-material-template-v1",
        release_lane: str = "local",
        user_daily_limit: int = 10,
        user_active_limit: int = 2,
        global_daily_limit: int = 20,
        global_queue_limit: int = 50,
        consultation_intent_ttl_seconds: int = 300,
    ) -> None:
        self.repository = repository
        self.object_store = object_store
        self.idempotency = idempotency
        self.enabled = enabled
        self.retention_hours = retention_hours
        self.model_name = model_name
        self.release_lane = release_lane
        self.user_daily_limit = user_daily_limit
        self.user_active_limit = user_active_limit
        self.global_daily_limit = global_daily_limit
        self.global_queue_limit = global_queue_limit
        if consultation_intent_ttl_seconds <= 0:
            raise ValueError("consultation_intent_ttl_seconds must be positive")
        self.consultation_intent_ttl_seconds = consultation_intent_ttl_seconds

    async def options(
        self, principal: Principal, application_id: UUID
    ) -> dict[str, Any]:
        self._citizen(principal)
        items = await self.repository.list_material_template_options(
            application_id, principal.account_id
        )
        return {"items": items, "total": len(items), "demo_data": True}

    async def consultation_options(
        self,
        principal: Principal,
        service_id: UUID | None = None,
        query: str | None = None,
    ) -> dict[str, Any]:
        self._citizen(principal)
        items = await self.repository.list_consultation_material_template_options(
            service_id, query
        )
        return {"items": items, "total": len(items), "demo_data": True}

    async def search_consultation_options(
        self, principal: Principal, query: str
    ) -> dict[str, Any]:
        self._citizen(principal)
        items = await self.repository.search_consultation_material_template_options(
            query
        )
        return {"items": items, "total": len(items), "demo_data": True}

    async def create_consultation_intent(
        self,
        principal: Principal,
        session_id: UUID,
        service_id: UUID,
        requirement_code: str,
        template_id: UUID,
        request_text: str | None = None,
    ) -> dict[str, Any]:
        self._citizen(principal)
        self._require_enabled()
        normalized = self._normalize_request_text(request_text)
        return await self.repository.create_consultation_material_intent(
            principal.account_id,
            session_id,
            service_id,
            requirement_code,
            template_id,
            normalized,
            datetime.now(timezone.utc)
            + timedelta(seconds=self.consultation_intent_ttl_seconds),
        )

    async def consultation_intent_states(
        self,
        principal: Principal,
        session_id: UUID,
        intent_ids: tuple[UUID, ...],
    ) -> dict[UUID, dict[str, Any]]:
        self._citizen(principal)
        return await self.repository.get_consultation_material_intent_states(
            principal.account_id,
            session_id,
            intent_ids,
            datetime.now(timezone.utc),
        )

    async def latest_pending_consultation_intent(
        self, principal: Principal, session_id: UUID
    ) -> dict[str, Any] | None:
        self._citizen(principal)
        return await self.repository.get_latest_pending_consultation_material_intent(
            principal.account_id, session_id, datetime.now(timezone.utc)
        )

    async def confirm_consultation_intent(
        self,
        principal: Principal,
        session_id: UUID,
        intent_id: UUID,
    ) -> dict[str, Any]:
        self._citizen(principal)
        self._require_enabled()
        return await self.repository.confirm_consultation_material_intent(
            principal.account_id,
            session_id,
            intent_id,
            datetime.now(timezone.utc) + timedelta(hours=self.retention_hours),
            self.model_name,
            self.release_lane,
            self.user_daily_limit,
            self.user_active_limit,
            self.global_daily_limit,
            self.global_queue_limit,
        )

    async def create(
        self,
        principal: Principal,
        application_id: UUID,
        requirement_code: str,
        template_id: UUID,
        request_text: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._citizen(principal)
        self._require_enabled()
        normalized = self._normalize_request_text(request_text)

        async def operation() -> dict[str, Any]:
            return await self.repository.create_material_document_job(
                principal.account_id,
                application_id,
                requirement_code,
                template_id,
                normalized,
                datetime.now(timezone.utc) + timedelta(hours=self.retention_hours),
                self.model_name,
                self.release_lane,
                self.user_daily_limit,
                self.user_active_limit,
                self.global_daily_limit,
                self.global_queue_limit,
            )

        return await self.idempotency.execute(
            principal.account_id,
            f"material-document.create:{application_id}",
            idempotency_key,
            {
                "requirement_code": requirement_code,
                "template_id": str(template_id),
                "request_text": normalized,
            },
            operation,
        )

    async def status(
        self, principal: Principal, generation_id: UUID
    ) -> dict[str, Any]:
        self._citizen(principal)
        result = await self.repository.get_material_document_job_authorized(
            generation_id, principal.account_id
        )
        return {key: value for key, value in result.items() if key != "object_key"}

    async def download(
        self, principal: Principal, generation_id: UUID
    ) -> tuple[bytes, dict[str, Any]]:
        self._citizen(principal)
        metadata = await self.repository.get_material_document_job_authorized(
            generation_id, principal.account_id
        )
        status = MaterialDocumentStatus(metadata["status"])
        if status is MaterialDocumentStatus.EXPIRED:
            raise GoneError("生成文档已过期", "material_document_expired")
        if status is not MaterialDocumentStatus.READY:
            raise ConflictError("生成文档尚未就绪", "material_document_not_ready")
        object_key = metadata.get("object_key")
        if not isinstance(object_key, str) or not object_key:
            raise ConflictError("生成文档完整性异常", "material_document_integrity_failed")
        content = await self.object_store.get_bytes(
            self.object_store.generated_documents_bucket, object_key
        )
        digest = hashlib.sha256(content).hexdigest()
        if (
            not content
            or len(content) != metadata["size_bytes"]
            or digest != metadata["sha256"]
            or len(content) > MAX_GENERATED_DOCUMENT_BYTES
        ):
            raise ConflictError("生成文档完整性异常", "material_document_integrity_failed")
        return content, metadata

    @staticmethod
    def _citizen(principal: Principal) -> None:
        if principal.role is not Role.CITIZEN:
            raise PermissionDenied("材料模板仅向群众账号开放")

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise ConflictError(
                "材料模板生成功能尚未启用", "material_documents_disabled"
            )

    @staticmethod
    def _normalize_request_text(request_text: str | None) -> str | None:
        normalized = request_text.strip() if request_text else None
        if normalized and len(normalized) > 300:
            raise BusinessValidationError("材料生成要求不能超过 300 个字符")
        return normalized or None


class MaterialDocumentWorker:
    def __init__(
        self,
        repository: MaterialDocumentRepositoryPort,
        object_store: ObjectStorePort,
        analyzer: MaterialTemplateAnalyzerPort,
        page_renderer: TemplatePageRendererPort,
        docx_renderer: DocxMaterialRendererPort,
        *,
        lease_seconds: int,
        release_lane: str = "local",
        lease_heartbeat_seconds: float | None = None,
    ) -> None:
        self.repository = repository
        self.object_store = object_store
        self.analyzer = analyzer
        self.page_renderer = page_renderer
        self.docx_renderer = docx_renderer
        self.lease_seconds = lease_seconds
        self.release_lane = release_lane
        self.lease_heartbeat_seconds = lease_heartbeat_seconds

    async def run_once(self) -> bool:
        job = await self.repository.lease_material_document_job(
            self.lease_seconds, self.release_lane
        )
        if job is None:
            await self._expire()
            return False
        try:
            await self._run_leased_job(job)
        except Exception as exc:
            if isinstance(exc, (_WorkerFailure, MaterialDocumentProcessingError)):
                code = exc.code
            else:
                # Do not persist exception messages, provider response bodies,
                # URLs, credentials or third-party class names.
                code = "UNEXPECTED_WORKER_ERROR"
            await self.repository.fail_material_document_job(
                job.id, job.lease_token, str(code)[:64].upper()
            )
        await self._expire()
        return True

    async def _run_leased_job(self, job: LeasedMaterialDocumentJob) -> None:
        work = asyncio.create_task(
            self._process_job(job), name=f"material-document-{job.id}"
        )
        heartbeat = asyncio.create_task(
            self._renew_lease(job), name=f"material-document-lease-{job.id}"
        )
        done, _ = await asyncio.wait(
            {work, heartbeat}, return_when=asyncio.FIRST_COMPLETED
        )
        if work in done:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            work.result()
            return
        work.cancel()
        await asyncio.gather(work, return_exceptions=True)
        heartbeat.result()
        raise _WorkerFailure("LEASE_LOST")

    async def _renew_lease(self, job: LeasedMaterialDocumentJob) -> None:
        interval = self.lease_heartbeat_seconds
        if interval is None:
            interval = max(1.0, min(self.lease_seconds / 3, 30.0))
        while True:
            await asyncio.sleep(interval)
            renewed = await self.repository.renew_material_document_job_lease(
                job.id, job.lease_token, self.lease_seconds
            )
            if not renewed:
                raise _WorkerFailure("LEASE_LOST")

    async def _process_job(self, job: LeasedMaterialDocumentJob) -> None:
        output_key: str | None = None
        try:
            if job.model_name != self.analyzer.model_name:
                raise _WorkerFailure("MODEL_SEMANTICS_MISMATCH")
            if not job.source_object_key or not job.source_sha256:
                raise _WorkerFailure("TEMPLATE_SOURCE_MISSING")
            source = await self.object_store.get_bytes(
                self.object_store.material_templates_bucket,
                job.source_object_key,
            )
            if hashlib.sha256(source).hexdigest() != job.source_sha256:
                raise _WorkerFailure("TEMPLATE_SOURCE_INTEGRITY")
            pages = await self.page_renderer.render_pages(source)
            if not pages:
                raise _WorkerFailure("TEMPLATE_RENDER_EMPTY")
            analysis = await self.analyzer.analyze(
                page_images=pages,
                template_title=job.template_title,
                allowed_fields=job.allowed_fields,
                form_snapshot=job.form_snapshot,
                request_text=job.request_text,
            )
            if not set(analysis.fields).issubset(job.allowed_fields):
                raise _WorkerFailure("MODEL_SCHEMA_INVALID")
            result = await self.docx_renderer.render(
                mode=job.template_mode,
                template_key=job.template_key,
                template_title=job.template_title,
                source_docx=source,
                analysis=analysis,
            )
            if not result or len(result) > MAX_GENERATED_DOCUMENT_BYTES:
                raise _WorkerFailure("DOCX_OUTPUT_INVALID")
            digest = hashlib.sha256(result).hexdigest()
            output_key = f"generated-materials/{job.owner_account_id}/{job.id}.docx"
            await self.object_store.put_bytes(
                self.object_store.generated_documents_bucket,
                output_key,
                result,
                DOCX_CONTENT_TYPE,
            )
            filename = f"{job.template_title}-演示模板.docx"
            committed = await self.repository.complete_material_document_job(
                job.id,
                job.lease_token,
                output_key,
                filename,
                len(result),
                digest,
                self.analyzer.model_name,
                analysis.warnings,
            )
            if not committed:
                await self.object_store.delete(
                    self.object_store.generated_documents_bucket, output_key
                )
                output_key = None
                raise _WorkerFailure("LEASE_LOST")
            output_key = None
        except BaseException:
            if output_key is not None:
                try:
                    await self.object_store.delete(
                        self.object_store.generated_documents_bucket, output_key
                    )
                except Exception:
                    pass
            raise

    async def _expire(self) -> None:
        keys = await self.repository.expire_material_document_jobs(
            datetime.now(timezone.utc)
        )
        for key in keys:
            try:
                await self.object_store.delete(
                    self.object_store.generated_documents_bucket, key
                )
            except Exception:
                continue


class _WorkerFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
