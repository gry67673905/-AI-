from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import Response, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.boundaries.business_schemas import (
    AccountStatusRequest,
    AppointmentAdvanceRequest,
    AppointmentCreateRequest,
    AuthResponse,
    DeliveryAdvanceRequest,
    DeliveryCreateRequest,
    DepartmentCreateRequest,
    DraftApplicationRequest,
    EligibilityRequest,
    FeedbackRequest,
    FormUpdateRequest,
    HandoffCreateRequest,
    HandoffMessageRequest,
    LifecycleRequest,
    LoginRequest,
    LogoutRequest,
    MaterialEvaluationRequest,
    PaymentAdvanceRequest,
    PaymentCreateRequest,
    RefreshRequest,
    RegisterRequest,
    RequestCodeRequest,
    ReviewDecisionRequest,
    ServiceCreateRequest,
    ServiceVersionCreateRequest,
    StaffCreateRequest,
    StatusWriteRequest,
    VerificationCompleteRequest,
    VerificationCreateRequest,
    WindowCreateRequest,
)
from app.boundaries.chat_mapping import source_payload, to_chat_command
from app.application.dtos import Principal
from app.domain.enums import (
    AppointmentStatus,
    ApplicationStatus,
    DeliveryStatus,
    Role,
    ServiceStatus,
)
from app.errors import AuthenticationRequired, BusinessValidationError, PermissionDenied
from app.schemas import ChatRequest


_bearer = HTTPBearer(auto_error=False)


def _runtime(request: Request) -> Any:
    runtime = getattr(request.app.state.services, "business", None)
    if runtime is None:
        raise RuntimeError("business runtime is not configured")
    return runtime


async def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationRequired()
    return await _runtime(request).auth.authenticate(credentials.credentials)


async def optional_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal | None:
    if credentials is None:
        return None
    return await _runtime(request).auth.authenticate(credentials.credentials)


def _require_role(principal: Principal, role: Role) -> None:
    if principal.role is not role:
        raise PermissionDenied()


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


class AuthHttpBoundary:
    def __init__(self) -> None:
        self.router = APIRouter(prefix="/auth", tags=["认证（演示）"])
        self.router.add_api_route("/request-code", self.request_code, methods=["POST"])
        self.router.add_api_route("/register", self.register, methods=["POST"], response_model=AuthResponse)
        self.router.add_api_route("/login", self.login, methods=["POST"], response_model=AuthResponse)
        self.router.add_api_route("/refresh", self.refresh, methods=["POST"], response_model=AuthResponse)
        self.router.add_api_route("/logout", self.logout, methods=["POST"])
        self.router.add_api_route("/me", self.me, methods=["GET"])

    async def request_code(self, payload: RequestCodeRequest, request: Request) -> dict[str, object]:
        return await _runtime(request).auth.request_code(payload.destination, payload.purpose)

    async def register(self, payload: RegisterRequest, request: Request) -> dict[str, Any]:
        return await _runtime(request).auth.register(payload.username, payload.password, payload.display_name, payload.applicant_type, payload.verification_code)

    async def login(self, payload: LoginRequest, request: Request) -> dict[str, Any]:
        return await _runtime(request).auth.login(payload.username, payload.password)

    async def refresh(self, payload: RefreshRequest, request: Request) -> dict[str, Any]:
        return await _runtime(request).auth.refresh(payload.refresh_token)

    async def logout(self, payload: LogoutRequest, request: Request) -> dict[str, str]:
        return await _runtime(request).auth.logout(payload.refresh_token)

    async def me(self, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).auth.me(principal)


class CitizenPortalBoundary:
    def __init__(self) -> None:
        self.router = APIRouter(tags=["群众一网办"])
        self.router.add_api_route("/services", self.search_services, methods=["GET"])
        self.router.add_api_route("/services/{service_id}", self.service_details, methods=["GET"])
        self.router.add_api_route("/services/{service_id}/eligibility", self.eligibility, methods=["POST"])
        self.router.add_api_route("/services/{service_id}/materials", self.materials, methods=["GET"])
        self.router.add_api_route("/services/{service_id}/materials/evaluate", self.evaluate_materials, methods=["POST"])
        self.router.add_api_route("/services/{service_id}/process", self.process, methods=["GET"])
        self.router.add_api_route("/services/{service_id}/form", self.form, methods=["GET"])
        self.router.add_api_route("/services/{service_id}/windows", self.windows, methods=["GET"])
        self.router.add_api_route("/applications", self.create_application, methods=["POST"])
        self.router.add_api_route("/applications", self.list_applications, methods=["GET"])
        self.router.add_api_route("/applications/{application_id}", self.get_application, methods=["GET"])
        self.router.add_api_route("/applications/{application_id}/form", self.update_form, methods=["PATCH"])
        self.router.add_api_route("/applications/{application_id}/materials", self.upload_material, methods=["POST"])
        self.router.add_api_route("/applications/{application_id}/materials/{material_id}", self.download_material, methods=["GET"])
        self.router.add_api_route("/applications/{application_id}/submit", self.submit, methods=["POST"])
        self.router.add_api_route("/applications/{application_id}/supplement", self.supplement, methods=["POST"])
        self.router.add_api_route("/applications/{application_id}/withdraw", self.withdraw, methods=["POST"])
        self.router.add_api_route("/applications/{application_id}/discard", self.discard, methods=["POST"])
        self.router.add_api_route("/applications/{application_id}/timeline", self.timeline, methods=["GET"])
        self.router.add_api_route("/applications/{application_id}/delivery", self.delivery, methods=["POST"])
        self.router.add_api_route("/consultations", self.consultations, methods=["GET"])
        self.router.add_api_route("/consultations/feedback", self.feedback, methods=["POST"])
        self.router.add_api_route("/consultations/handoffs", self.create_handoff, methods=["POST"])
        self.router.add_api_route("/consultations/handoffs", self.list_handoffs, methods=["GET"])
        self.router.add_api_route("/consultations/handoffs/{ticket_id}/messages", self.add_handoff_message, methods=["POST"])
        self.router.add_api_route("/consultations/handoffs/{ticket_id}/messages", self.handoff_messages, methods=["GET"])
        self.router.add_api_route("/consultations/handoffs/{ticket_id}/cancel", self.cancel_handoff, methods=["POST"])

    async def search_services(self, request: Request, q: str | None = Query(default=None, max_length=100)) -> dict[str, Any]:
        return await _runtime(request).catalog.search(q)

    async def service_details(self, service_id: UUID, request: Request) -> dict[str, Any]:
        return await _runtime(request).catalog.details(service_id)

    async def eligibility(self, service_id: UUID, payload: EligibilityRequest, request: Request) -> dict[str, Any]:
        return await _runtime(request).catalog.evaluate_eligibility(service_id, payload.answers)

    async def materials(self, service_id: UUID, request: Request) -> dict[str, Any]:
        return await _runtime(request).catalog.evaluate_materials(service_id, {})

    async def evaluate_materials(self, service_id: UUID, payload: MaterialEvaluationRequest, request: Request) -> dict[str, Any]:
        return await _runtime(request).catalog.evaluate_materials(service_id, payload.answers)

    async def process(self, service_id: UUID, request: Request) -> dict[str, Any]:
        bundle = await _runtime(request).catalog.details(service_id)
        appointment_channels = (["WINDOW"] if bundle["requires_appointment"] else ["ONLINE", "WINDOW"]) if bundle["appointment_supported"] else []
        delivery_notice = (
            "可选择本地模拟邮寄；不会创建真实快递订单。"
            if bundle["mail_supported"]
            else "仅提供演示电子结果，不支持模拟邮寄。"
        )
        return {"service_id": service_id, "steps": bundle["process_steps"], "fee": {"required": bundle["fee_required"], "amount_cents": bundle["fee_cents"] if not bundle["fee_calculation"] else None, "calculation": bundle["fee_calculation"], "currency": "CNY", "notice": "仅生成本地模拟缴费订单"}, "delivery": {"supported": bundle["delivery_supported"], "options": bundle["delivery_options"], "mail_supported": bundle["mail_supported"], "demo_mail_supported": bundle["demo_mail_supported"], "notice": delivery_notice}, "appointment": {"supported": bundle["appointment_supported"], "required": bundle["requires_appointment"], "channels": appointment_channels}, "notice": bundle["notice"], "demo_data": True}

    async def form(self, service_id: UUID, request: Request) -> dict[str, Any]:
        bundle = await _runtime(request).catalog.details(service_id)
        return {"service_id": service_id, "schema": bundle["form_schema"], "demo_data": True}

    async def windows(self, service_id: UUID, request: Request) -> dict[str, Any]:
        bundle = await _runtime(request).catalog.details(service_id)
        return {"items": bundle["windows"], "total": len(bundle["windows"]), "map_notice": "坐标仅用于演示，不能用于真实导航。", "demo_data": True}

    async def create_application(
        self, payload: DraftApplicationRequest, request: Request,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=128)] = None,
    ) -> dict[str, Any]:
        runtime = _runtime(request)
        operation = lambda: runtime.applications.create_draft(principal, payload.service_id, payload.initial_form_data)
        if idempotency_key:
            return await runtime.idempotency.execute(principal.account_id, "application.create", idempotency_key, payload.model_dump(mode="json"), operation)
        return await operation()

    async def list_applications(self, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).applications.list(principal)

    async def get_application(self, application_id: UUID, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).applications.get(principal, application_id)

    async def update_form(self, application_id: UUID, payload: FormUpdateRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).applications.update_form(principal, application_id, payload.data, payload.version)

    async def upload_material(
        self, application_id: UUID, request: Request,
        principal: Annotated[Principal, Depends(current_principal)],
        requirement_code: Annotated[str, Form(min_length=1, max_length=64)],
        file: Annotated[UploadFile, File()],
        synthetic_data_confirmed: Annotated[bool, Form()] = True,
    ) -> dict[str, Any]:
        if not synthetic_data_confirmed:
            raise PermissionDenied("本地演示只允许上传合成材料")
        coordinator = _runtime(request).applications
        content = await file.read(coordinator.max_material_bytes + 1)
        return await coordinator.upload_material(principal, application_id, requirement_code, file.filename or "material", file.content_type or "application/octet-stream", content)

    async def download_material(
        self,
        application_id: UUID,
        material_id: UUID,
        request: Request,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Response:
        content, metadata = await _runtime(request).applications.download_material(
            principal, application_id, material_id
        )
        extension = {
            "application/pdf": ".pdf",
            "image/jpeg": ".jpg",
            "image/png": ".png",
        }.get(metadata["content_type"], ".bin")
        return Response(
            content=content,
            media_type=metadata["content_type"],
            headers={
                "Content-Disposition": f'attachment; filename="demo-material{extension}"',
                "X-Content-SHA256": metadata["sha256"],
                "Cache-Control": "private, no-store",
            },
        )

    async def submit(self, application_id: UUID, payload: StatusWriteRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]) -> dict[str, Any]:
        return await _runtime(request).applications.submit(principal, application_id, payload.version, idempotency_key)

    async def supplement(self, application_id: UUID, payload: FormUpdateRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).applications.update_form(principal, application_id, payload.data, payload.version)

    async def withdraw(self, application_id: UUID, payload: StatusWriteRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]) -> dict[str, Any]:
        return await _runtime(request).applications.withdraw(principal, application_id, payload.version, payload.comment, idempotency_key)

    async def discard(self, application_id: UUID, payload: StatusWriteRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]) -> dict[str, Any]:
        return await _runtime(request).applications.discard(principal, application_id, payload.version, idempotency_key)

    async def timeline(self, application_id: UUID, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).applications.timeline(principal, application_id)

    async def delivery(self, application_id: UUID, payload: DeliveryCreateRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]) -> dict[str, Any]:
        return await _runtime(request).deliveries.create(
            principal, application_id, payload.recipient, payload.address,
            idempotency_key,
        )

    async def consultations(self, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).consultations.list(principal)

    async def feedback(self, payload: FeedbackRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).consultations.feedback(
            principal, payload.session_id, payload.rating, payload.comment
        )

    async def create_handoff(self, payload: HandoffCreateRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).handoffs.create(principal, payload.session_id, payload.subject, payload.department_id)

    async def list_handoffs(self, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).handoffs.list(principal)

    async def add_handoff_message(self, ticket_id: UUID, payload: HandoffMessageRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).handoffs.add_message(
            principal, ticket_id, payload.content
        )

    async def handoff_messages(self, ticket_id: UUID, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).handoffs.messages(principal, ticket_id)

    async def cancel_handoff(self, ticket_id: UUID, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]) -> dict[str, Any]:
        return await _runtime(request).handoffs.cancel(
            principal, ticket_id, idempotency_key
        )


class StaffWorkbenchBoundary:
    def __init__(self) -> None:
        self.router = APIRouter(prefix="/staff", tags=["工作人员"])
        self.router.add_api_route("/tasks", self.tasks, methods=["GET"])
        self.router.add_api_route("/tasks/{task_id}/claim", self.claim, methods=["POST"])
        for action in ("supplement", "reject", "approve", "complete"):
            self.router.add_api_route(f"/applications/{{application_id}}/{action}", getattr(self, action), methods=["POST"])
        self.router.add_api_route("/handoffs", self.handoffs, methods=["GET"])
        self.router.add_api_route("/handoffs/{ticket_id}/messages", self.message, methods=["POST"])
        self.router.add_api_route("/handoffs/{ticket_id}/resolve", self.resolve, methods=["POST"])

    async def tasks(self, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).reviews.tasks(principal)

    async def claim(self, task_id: UUID, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]) -> dict[str, Any]:
        return await _runtime(request).reviews.claim(principal, task_id, idempotency_key)

    async def _decision(self, action: str, application_id: UUID, payload: ReviewDecisionRequest, request: Request, principal: Principal, key: str) -> dict[str, Any]:
        return await _runtime(request).reviews.decide(principal, application_id, action, payload.version, payload.comment, payload.require_payment, key)

    async def supplement(self, application_id: UUID, payload: ReviewDecisionRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key")]) -> dict[str, Any]:
        return await self._decision("supplement", application_id, payload, request, principal, idempotency_key)

    async def reject(self, application_id: UUID, payload: ReviewDecisionRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key")]) -> dict[str, Any]:
        return await self._decision("reject", application_id, payload, request, principal, idempotency_key)

    async def approve(self, application_id: UUID, payload: ReviewDecisionRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key")]) -> dict[str, Any]:
        return await self._decision("approve", application_id, payload, request, principal, idempotency_key)

    async def complete(self, application_id: UUID, payload: ReviewDecisionRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key")]) -> dict[str, Any]:
        return await self._decision("complete", application_id, payload, request, principal, idempotency_key)

    async def handoffs(self, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        _require_role(principal, Role.STAFF)
        return await _runtime(request).handoffs.list(principal)

    async def message(self, ticket_id: UUID, payload: HandoffMessageRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).handoffs.add_message(
            principal, ticket_id, payload.content
        )

    async def resolve(self, ticket_id: UUID, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).handoffs.resolve(principal, ticket_id)


class AdminConsoleBoundary:
    def __init__(self) -> None:
        self.router = APIRouter(prefix="/admin", tags=["管理员"])
        self.router.add_api_route("/departments", self.departments, methods=["GET"])
        self.router.add_api_route("/departments", self.create_department, methods=["POST"])
        self.router.add_api_route("/windows", self.windows, methods=["GET"])
        self.router.add_api_route("/windows", self.create_window, methods=["POST"])
        self.router.add_api_route("/staff", self.create_staff, methods=["POST"])
        self.router.add_api_route("/accounts", self.accounts, methods=["GET"])
        self.router.add_api_route("/accounts/{account_id}/status", self.account_status, methods=["POST"])
        self.router.add_api_route("/services", self.services, methods=["GET"])
        self.router.add_api_route("/services", self.create_service, methods=["POST"])
        self.router.add_api_route("/services/{service_id}/versions", self.create_version, methods=["POST"])
        self.router.add_api_route("/services/{service_id}/lifecycle", self.lifecycle, methods=["POST"])
        self.router.add_api_route("/knowledge", self.upload_knowledge, methods=["POST"])
        self.router.add_api_route("/knowledge/{job_id}/retry", self.retry_knowledge, methods=["POST"])
        self.router.add_api_route("/knowledge/{job_id}/archive", self.archive_knowledge, methods=["POST"])
        self.router.add_api_route("/audit", self.audit, methods=["GET"])
        self.router.add_api_route("/metrics", self.metrics, methods=["GET"])

    @staticmethod
    def _admin(principal: Principal) -> None: _require_role(principal, Role.ADMIN)

    async def departments(self, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).admin.departments(principal)

    async def create_department(self, payload: DepartmentCreateRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).admin.create_department(
            principal, payload.code, payload.name
        )

    async def windows(self, request: Request, principal: Annotated[Principal, Depends(current_principal)], department_id: UUID | None = None) -> dict[str, Any]:
        return await _runtime(request).admin.windows(principal, department_id)

    async def create_window(self, payload: WindowCreateRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).admin.create_window(
            principal, payload.model_dump(mode="json")
        )

    async def create_staff(self, payload: StaffCreateRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).admin.create_staff(
            principal, payload.username, payload.password, payload.display_name,
            payload.department_id, payload.window_id,
        )

    async def accounts(self, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).admin.accounts(principal)

    async def account_status(self, account_id: UUID, payload: AccountStatusRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).admin.set_account_status(
            principal, account_id, payload.active
        )

    async def services(self, request: Request, principal: Annotated[Principal, Depends(current_principal)], q: str | None = None) -> dict[str, Any]:
        return await _runtime(request).admin.services(principal, q)

    async def create_service(self, payload: ServiceCreateRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).admin.create_service(
            principal, payload.model_dump(mode="json")
        )

    async def create_version(self, service_id: UUID, payload: ServiceVersionCreateRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).admin.create_version(
            principal, service_id, payload.model_dump(mode="json")
        )

    async def lifecycle(self, service_id: UUID, payload: LifecycleRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key")]) -> dict[str, Any]:
        return await _runtime(request).admin.lifecycle(
            principal, service_id, ServiceStatus(payload.target_status),
            payload.version_id, idempotency_key,
        )

    async def upload_knowledge(self, request: Request, principal: Annotated[Principal, Depends(current_principal)], file: Annotated[UploadFile, File()], title: Annotated[str, Form(min_length=1, max_length=200)], source: Annotated[str, Form(max_length=255)] = "demo://admin-upload") -> dict[str, Any]:
        self._admin(principal)
        coordinator = _runtime(request).knowledge
        content = await file.read(coordinator.max_knowledge_bytes + 1)
        if len(content) > coordinator.max_knowledge_bytes:
            raise BusinessValidationError("知识文件必须非空且不超过 20MB")
        return await coordinator.upload(principal, file.filename or "knowledge.txt", file.content_type or "application/octet-stream", content, title, source)

    async def retry_knowledge(self, job_id: UUID, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]) -> dict[str, Any]:
        return await _runtime(request).knowledge.retry(
            principal, job_id, idempotency_key
        )

    async def archive_knowledge(self, job_id: UUID, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]) -> dict[str, Any]:
        return await _runtime(request).knowledge.archive(
            principal, job_id, idempotency_key
        )

    async def audit(self, request: Request, principal: Annotated[Principal, Depends(current_principal)], limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
        return await _runtime(request).admin.audits(principal, limit)

    async def metrics(self, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).admin.metrics(principal)


class OperationsBoundary:
    def __init__(self) -> None:
        self.router = APIRouter(tags=["预约与模拟能力"])
        self.router.add_api_route("/appointments", self.appointments, methods=["GET"])
        self.router.add_api_route("/appointments", self.create_appointment, methods=["POST"])
        self.router.add_api_route("/appointments/{appointment_id}/cancel", self.cancel_appointment, methods=["POST"])
        self.router.add_api_route("/appointments/{appointment_id}/status", self.advance_appointment, methods=["POST"])
        self.router.add_api_route("/payments", self.create_payment, methods=["POST"])
        self.router.add_api_route("/payments/{payment_id}/pay", self.pay, methods=["POST"])
        self.router.add_api_route("/payments/{payment_id}/cancel", self.cancel_payment, methods=["POST"])
        self.router.add_api_route("/verifications", self.create_verification, methods=["POST"])
        self.router.add_api_route("/verifications/{verification_id}/complete", self.complete_verification, methods=["POST"])
        self.router.add_api_route("/deliveries/{delivery_id}/status", self.advance_delivery, methods=["POST"])
        self.router.add_api_route("/deliveries/{delivery_id}/cancel", self.cancel_delivery, methods=["POST"])

    async def appointments(self, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, Any]:
        return await _runtime(request).appointments.list(principal)

    async def create_appointment(self, payload: AppointmentCreateRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key")]) -> dict[str, Any]:
        return await _runtime(request).appointments.create(principal, payload.service_id, payload.window_id, payload.slot_start, idempotency_key)

    async def cancel_appointment(self, appointment_id: UUID, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key")]) -> dict[str, Any]:
        return await _runtime(request).appointments.cancel(principal, appointment_id, idempotency_key)

    async def advance_appointment(self, appointment_id: UUID, payload: AppointmentAdvanceRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]) -> dict[str, Any]:
        return await _runtime(request).appointments.advance(
            principal, appointment_id, AppointmentStatus(payload.status), idempotency_key
        )

    async def create_payment(self, payload: PaymentCreateRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key")]) -> dict[str, Any]:
        return await _runtime(request).payments.create(principal, payload.application_id, idempotency_key)

    async def pay(self, payment_id: UUID, payload: PaymentAdvanceRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key")]) -> dict[str, Any]:
        return await _runtime(request).payments.pay(principal, payment_id, payload.outcome, idempotency_key)

    async def cancel_payment(self, payment_id: UUID, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]) -> dict[str, Any]:
        return await _runtime(request).payments.cancel(
            principal, payment_id, idempotency_key
        )

    async def create_verification(self, payload: VerificationCreateRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key")]) -> dict[str, Any]:
        return await _runtime(request).verifications.create(
            principal, payload.application_id, idempotency_key
        )

    async def complete_verification(self, verification_id: UUID, payload: VerificationCompleteRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key")]) -> dict[str, Any]:
        return await _runtime(request).verifications.complete(
            principal, verification_id, payload.outcome, idempotency_key
        )

    async def advance_delivery(self, delivery_id: UUID, payload: DeliveryAdvanceRequest, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]) -> dict[str, Any]:
        return await _runtime(request).deliveries.advance(
            principal, delivery_id, DeliveryStatus(payload.status), idempotency_key
        )

    async def cancel_delivery(self, delivery_id: UUID, request: Request, principal: Annotated[Principal, Depends(current_principal)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]) -> dict[str, Any]:
        return await _runtime(request).deliveries.cancel(
            principal, delivery_id, idempotency_key
        )


class VoiceStreamBoundary:
    def __init__(self) -> None:
        self.router = APIRouter(tags=["流式咨询"])
        self.router.add_api_route("/chat/stream", self.stream, methods=["POST"])

    async def stream(self, payload: ChatRequest, request: Request, principal: Annotated[Principal | None, Depends(optional_principal)]) -> StreamingResponse:
        if payload.application_id and principal is None:
            raise AuthenticationRequired("查询办件状态必须登录")
        coordinator = _runtime(request).consultations

        async def events():
            try:
                result = await coordinator.chat(to_chat_command(payload), principal)
                yield _sse("meta", {"request_id": result.request_id, "session_id": result.session_id, "sources": [source_payload(item) for item in result.sources], "candidate_services": result.candidate_services, "clarification_required": result.clarification_required, "demo_data": True})
                for start in range(0, len(result.answer), 24):
                    yield _sse("delta", {"text": result.answer[start:start + 24]})
                    await asyncio.sleep(0)
                yield _sse("done", {"request_id": result.request_id, "session_id": result.session_id, "warnings": result.warnings, "suggested_actions": result.suggested_actions})
            except Exception as exc:
                code = getattr(exc, "code", "stream_failed")
                message = getattr(exc, "message", "流式咨询暂不可用")
                yield _sse("error", {"code": code, "message": message})

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def build_business_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    for boundary in (
        AuthHttpBoundary(), CitizenPortalBoundary(), StaffWorkbenchBoundary(),
        AdminConsoleBoundary(), OperationsBoundary(), VoiceStreamBoundary(),
    ):
        router.include_router(boundary.router)
    return router
