from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.entities import Account, Application, MaterialRequirement
from app.application.material_documents import LeasedMaterialDocumentJob
from app.application.dtos import NavigationCatalogRowData
from app.domain.enums import (
    ApplicantType,
    AppointmentStatus,
    ApplicationStatus,
    DeliveryStatus,
    ConsultationMaterialIntentStatus,
    DigitalHumanIntentStatus,
    HandoffStatus,
    KnowledgeStatus,
    MaterialDocumentScope,
    MaterialDocumentStatus,
    MaterialTemplateMode,
    PaymentStatus,
    Role,
    ServiceStatus,
)
from app.domain.policies import (
    ApplicationStateMachine,
    AuthorizedCaseQueryService,
    AppointmentStateMachine,
    DeliveryStateMachine,
    DomainRuleViolation,
    HandoffAccessPolicy,
    HandoffStateMachine,
    KnowledgeStateMachine,
    PaymentStateMachine,
    ServiceLifecyclePolicy,
)
from app.errors import (
    AuthenticationRequired,
    BusinessValidationError,
    ConflictError,
    GoneError,
    PermissionDenied,
    ResourceNotFound,
    TooManyRequests,
)
from app.infrastructure.catalog_seed import (
    DEMO_DEPARTMENTS,
    DEMO_SERVICES,
    DEMO_WINDOWS,
    demo_delivery_contract,
)
from app.infrastructure.records import (
    AccountRecord,
    ApplicationEventRecord,
    ApplicationMaterialRecord,
    ApplicationRecord,
    AppointmentRecord,
    BusinessAuditEventRecord,
    ConsultationMaterialIntentRecord,
    ConsultationFeedbackRecord,
    DeliveryOrderRecord,
    DepartmentRecord,
    DigitalHumanActionIntentRecord,
    EligibilityRuleRecord,
    FaqEntryRecord,
    GovernmentServiceRecord,
    HandoffMessageRecord,
    HandoffTicketRecord,
    IdempotencyRecord,
    KnowledgeChunkRecord,
    KnowledgeIndexJobRecord,
    MaterialRequirementRecord,
    MaterialDocumentJobRecord,
    MaterialTemplateRecord,
    PaymentOrderRecord,
    PolicySourceRecord,
    ProcessStepRecord,
    RefreshTokenRecord,
    ReviewTaskRecord,
    ServiceVersionRecord,
    ServiceWindowRecord,
    ServiceWindowLinkRecord,
    StaffAssignmentRecord,
    VerificationSessionRecord,
)
from app.models import ChatMessage, ChatSession, KnowledgeDocument
from app.security import hash_token, redact_sensitive


def _account(record: AccountRecord) -> Account:
    return Account(
        id=record.id,
        username=record.username,
        display_name=record.display_name,
        role=Role(record.role),
        applicant_type=ApplicantType(record.applicant_type) if record.applicant_type else None,
        active=record.active,
        token_version=record.token_version,
    )


def account_view(record: AccountRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "username": record.username,
        "display_name": record.display_name,
        "role": record.role,
        "applicant_type": record.applicant_type,
        "active": record.active,
        "department_id": record.department_id,
        "demo_data": True,
    }


def application_view(record: ApplicationRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "service_id": record.service_id,
        "service_version_id": record.service_version_id,
        "applicant_id": record.applicant_id,
        "status": record.status,
        "form_data": record.form_data,
        "version": record.version,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "demo_data": True,
    }


def _project_form_snapshot(
    form_data: dict[str, Any], allowed_fields: list[str]
) -> dict[str, Any]:
    """Copy only allowlisted scalar demo values into the short-lived job."""

    snapshot: dict[str, Any] = {}
    for dotted in allowed_fields:
        current: Any = form_data
        for part in dotted.split("."):
            if not isinstance(current, dict) or part not in current:
                current = None
                break
            current = current[part]
        bounded = _bounded_form_value(current)
        if bounded is None:
            continue
        target = snapshot
        parts = dotted.split(".")
        for part in parts[:-1]:
            child = target.get(part)
            if not isinstance(child, dict):
                child = {}
                target[part] = child
            target = child
        target[parts[-1]] = bounded
    return snapshot


_MATERIAL_DOCUMENT_ACTIVE_STATUSES = (
    MaterialDocumentStatus.QUEUED.value,
    MaterialDocumentStatus.RUNNING.value,
)


async def _enforce_material_document_job_limits(
    session: AsyncSession,
    owner_account_id: UUID,
    now: datetime,
    *,
    user_daily_limit: int,
    user_active_limit: int,
    global_daily_limit: int,
    global_queue_limit: int,
) -> None:
    """Serialize admission so count checks and the following insert are atomic."""

    await session.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "hashtextextended(:name, 0))"
        ),
        {"name": "smart-gov:material-document-admission:v1"},
    )
    day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    daily_count = await session.scalar(
        select(func.count(MaterialDocumentJobRecord.id)).where(
            MaterialDocumentJobRecord.owner_account_id == owner_account_id,
            MaterialDocumentJobRecord.created_at >= day_start,
        )
    )
    if int(daily_count or 0) >= user_daily_limit:
        raise TooManyRequests(
            "今日材料模板生成额度已用完，请明日再试",
            "material_document_daily_limit_exceeded",
        )
    global_daily_count = await session.scalar(
        select(func.count(MaterialDocumentJobRecord.id)).where(
            MaterialDocumentJobRecord.created_at >= day_start,
        )
    )
    if int(global_daily_count or 0) >= global_daily_limit:
        raise TooManyRequests(
            "今日材料模板生成总额度已用完，请明日再试",
            "material_document_global_daily_limit_exceeded",
        )
    user_active_count = await session.scalar(
        select(func.count(MaterialDocumentJobRecord.id)).where(
            MaterialDocumentJobRecord.owner_account_id == owner_account_id,
            MaterialDocumentJobRecord.status.in_(_MATERIAL_DOCUMENT_ACTIVE_STATUSES),
            MaterialDocumentJobRecord.expires_at > now,
        )
    )
    if int(user_active_count or 0) >= user_active_limit:
        raise TooManyRequests(
            "已有材料模板正在生成，请完成后再试",
            "material_document_user_active_limit_exceeded",
        )
    global_active_count = await session.scalar(
        select(func.count(MaterialDocumentJobRecord.id)).where(
            MaterialDocumentJobRecord.status.in_(_MATERIAL_DOCUMENT_ACTIVE_STATUSES),
            MaterialDocumentJobRecord.expires_at > now,
        )
    )
    if int(global_active_count or 0) >= global_queue_limit:
        raise TooManyRequests(
            "材料模板生成队列繁忙，请稍后再试",
            "material_document_global_queue_limit_exceeded",
        )


async def _require_material_document_service_published(
    session: AsyncSession, service_id: UUID
) -> GovernmentServiceRecord:
    """Lock and re-check publication in the job-admission transaction."""

    service = await session.get(
        GovernmentServiceRecord, service_id, with_for_update=True
    )
    if service is None or service.status != ServiceStatus.PUBLISHED.value:
        raise ConflictError(
            "事项已下架，当前不能生成材料",
            "material_document_service_unavailable",
        )
    return service


def _bounded_form_value(value: Any, depth: int = 0) -> Any:
    if depth > 2:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value[:1000] if isinstance(value, str) else value
    if isinstance(value, list) and len(value) <= 50:
        result = [_bounded_form_value(item, depth + 1) for item in value]
        return result if all(item is not None for item in result) else None
    if isinstance(value, dict) and len(value) <= 16:
        result = {
            str(key)[:64]: _bounded_form_value(item, depth + 1)
            for key, item in value.items()
        }
        return result if all(item is not None for item in result.values()) else None
    return None


def _material_document_view(
    record: MaterialDocumentJobRecord, *, include_object: bool = False
) -> dict[str, Any]:
    scope = record.scope or MaterialDocumentScope.APPLICATION.value
    result: dict[str, Any] = {
        "generation_id": record.id,
        "scope": scope,
        "service_id": record.service_id,
        "service_version_id": record.service_version_id,
        "application_id": record.application_id,
        "consultation_session_id": record.consultation_session_id,
        "requirement_code": record.requirement_code,
        "status": record.status,
        "filename": record.filename,
        "size_bytes": record.size_bytes,
        "sha256": record.sha256,
        "expires_at": record.expires_at,
        "warnings": list(record.warnings or []),
        "error_code": record.error_code,
        "demo_data": True,
    }
    if include_object:
        result["object_key"] = record.output_object_key
    return result


def _consultation_material_intent_view(
    intent: ConsultationMaterialIntentRecord,
    requirement: MaterialRequirementRecord,
    template: MaterialTemplateRecord,
    service_version: ServiceVersionRecord,
    *,
    generation_id: UUID | None = None,
) -> dict[str, Any]:
    return {
        "intent_id": intent.id,
        "session_id": intent.session_id,
        "service_id": intent.service_id,
        "service_version_id": intent.service_version_id,
        "service_title": service_version.title,
        "requirement_code": intent.requirement_code,
        "requirement_name": requirement.name,
        "template_id": intent.template_id,
        "template_key": template.template_key,
        "template_title": template.title,
        "mode": template.mode,
        "notice": template.notice,
        "status": intent.status,
        "expires_at": intent.expires_at,
        "confirmed_at": intent.confirmed_at,
        "generation_id": generation_id,
        "requires_confirmation": intent.status
        == ConsultationMaterialIntentStatus.PENDING.value,
        "demo_data": True,
    }


def _application(record: ApplicationRecord) -> Application:
    return Application(
        id=record.id,
        applicant_id=record.applicant_id,
        service_id=record.service_id,
        service_version_id=record.service_version_id,
        status=ApplicationStatus(record.status),
        form_data=dict(record.form_data),
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


_REVIEW_TASK_APPLICATION_STATUSES = {
    ApplicationStatus.SUBMITTED.value,
    ApplicationStatus.IN_REVIEW.value,
    ApplicationStatus.PROCESSING.value,
}


class BusinessRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions
        self._application_states = ApplicationStateMachine()
        self._case_access = AuthorizedCaseQueryService()
        self._service_states = ServiceLifecyclePolicy()
        self._handoff_access = HandoffAccessPolicy()
        self._handoff_states = HandoffStateMachine()
        self._appointment_states = AppointmentStateMachine()
        self._delivery_states = DeliveryStateMachine()
        self._payment_states = PaymentStateMachine()
        self._knowledge_states = KnowledgeStateMachine()
        self._uow_session: ContextVar[AsyncSession | None] = ContextVar(
            "business_uow_session", default=None
        )

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[AsyncSession]:
        active = self._uow_session.get()
        if active is not None:
            yield active
            return
        async with self.sessions.begin() as session:  # root transaction
            yield session

    async def execute_idempotent(
        self,
        actor_id: UUID,
        scope: str,
        key: str,
        request_hash: str,
        operation: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Run database mutations and the idempotency record in one UoW.

        A PostgreSQL transaction advisory lock serializes the same actor/scope/key
        across processes. Repository mutation methods reuse this session through
        a context variable, so their domain changes and response record commit or
        roll back together.
        """

        lock_name = f"{actor_id}:{scope}:{key}"
        async with self.sessions.begin() as session:  # idempotent root transaction
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:name, 0))"),
                {"name": lock_name},
            )
            existing = await session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.actor_id == actor_id,
                    IdempotencyRecord.scope == scope,
                    IdempotencyRecord.idempotency_key == key,
                )
            )
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise ConflictError(
                        "同一 Idempotency-Key 不能用于不同请求",
                        "idempotency_key_reused",
                    )
                return existing.response_json
            token = self._uow_session.set(session)
            try:
                result = await operation()
                safe = redact_sensitive(result)
                session.add(
                    IdempotencyRecord(
                        actor_id=actor_id,
                        scope=scope,
                        idempotency_key=key,
                        request_hash=request_hash,
                        status_code=200,
                        response_json=safe,
                    )
                )
                await session.flush()
                return safe
            finally:
                self._uow_session.reset(token)

    async def seed_demo_catalog(
        self,
        admin_username: str,
        admin_hash: str,
        staff_username: str,
        staff_hash: str,
    ) -> None:
        async with self._transaction() as session:
            # Serialize SELECT-then-INSERT seeding across API replicas. The
            # transaction-scoped lock releases automatically on commit/rollback
            # and leaves ordinary business writes unaffected.
            await session.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended(:name, 0))"
                ),
                {"name": "smart-gov:business-seed:v2"},
            )
            departments: dict[str, DepartmentRecord] = {}
            for item in DEMO_DEPARTMENTS:
                record = await session.scalar(
                    select(DepartmentRecord).where(DepartmentRecord.code == item["code"])
                )
                if record is None:
                    record = DepartmentRecord(code=item["code"], name=item["name"], active=True)
                    session.add(record)
                    await session.flush()
                departments[item["code"]] = record

            windows: dict[str, ServiceWindowRecord] = {}
            for item in DEMO_WINDOWS:
                record = await session.scalar(
                    select(ServiceWindowRecord).where(ServiceWindowRecord.code == item["code"])
                )
                if record is None:
                    record = ServiceWindowRecord(
                        code=item["code"], department_id=departments[item["department"]].id,
                        name=item["name"], address=item["address"], latitude=item["latitude"],
                        longitude=item["longitude"], city_code="DEMO",
                        coordinate_type="GCJ02", data_mode="DEMO",
                        source_reference="demo://navigation-catalog",
                        opening_hours="工作日 09:00-17:00",
                        capacity_per_slot=10, active=True,
                    )
                    session.add(record)
                    await session.flush()
                elif record.data_mode == "DEMO":
                    record.city_code = "DEMO"
                    record.coordinate_type = "GCJ02"
                    record.source_reference = "demo://navigation-catalog"
                windows[item["code"]] = record

            admin = await session.scalar(select(AccountRecord).where(AccountRecord.username == admin_username.lower()))
            if admin is None:
                admin = AccountRecord(
                    username=admin_username.lower(), password_hash=admin_hash,
                    display_name="演示管理员", role=Role.ADMIN.value, applicant_type=None,
                    active=True, token_version=0, profile_json={"demo": True},
                )
                session.add(admin)

            staff = await session.scalar(select(AccountRecord).where(AccountRecord.username == staff_username.lower()))
            if staff is None:
                staff = AccountRecord(
                    username=staff_username.lower(), password_hash=staff_hash,
                    display_name="演示工作人员", role=Role.STAFF.value, applicant_type=None,
                    active=True, token_version=0,
                    department_id=departments["HUMAN_RESOURCES"].id, profile_json={"demo": True},
                )
                session.add(staff)
                await session.flush()
            assignment = await session.scalar(
                select(StaffAssignmentRecord).where(
                    StaffAssignmentRecord.account_id == staff.id,
                    StaffAssignmentRecord.department_id == departments["HUMAN_RESOURCES"].id,
                )
            )
            if assignment is None:
                session.add(
                    StaffAssignmentRecord(
                        account_id=staff.id, department_id=departments["HUMAN_RESOURCES"].id,
                        window_id=windows["HRSS-CENTER-01"].id, active=True,
                    )
                )

            for item in DEMO_SERVICES:
                service = await session.scalar(
                    select(GovernmentServiceRecord).where(GovernmentServiceRecord.code == item["code"])
                )
                created_service = service is None
                if service is None:
                    service = GovernmentServiceRecord(
                        code=item["code"], external_item_id=item["external_item_id"],
                        department_id=departments[item["department"]].id,
                        window_id=windows[item["window"]].id,
                        applicant_type=item["applicant_type"], status=ServiceStatus.PUBLISHED.value,
                    )
                    session.add(service)
                    await session.flush()
                service.handling_mode = item["handling_mode"]
                service.online_status = item["online_status"]
                service.status_reason = item["status_reason"]
                service.status_updated_at = datetime.now(timezone.utc)
                link = await session.get(
                    ServiceWindowLinkRecord,
                    (service.id, windows[item["window"]].id),
                )
                if link is None:
                    session.add(
                        ServiceWindowLinkRecord(
                            service_id=service.id,
                            window_id=windows[item["window"]].id,
                            priority=0,
                            active=True,
                        )
                    )
                else:
                    link.priority = 0
                    link.active = True
                if not created_service and service.current_version_id is not None:
                    continue
                version = ServiceVersionRecord(
                    service_id=service.id, version=1, title=item["title"], summary=item["summary"],
                    form_schema=item.get("form_schema", {}), fee_cents=item.get("fee_cents", 0),
                    fee_required=item.get("fee_required", False),
                    fee_calculation=item.get("fee_calculation"),
                    appointment_supported=item.get("appointment_supported", False),
                    requires_appointment=item.get("requires_appointment", False),
                    requires_verification=item.get("requires_verification", False),
                    delivery_supported=item.get("delivery_supported", False), immutable=True,
                    published_at=datetime.now(timezone.utc),
                )
                session.add(version)
                await session.flush()
                service.current_version_id = version.id
                for index, (rule, message) in enumerate(item.get("rules", [])):
                    session.add(EligibilityRuleRecord(
                        service_version_id=version.id, rule_json=rule,
                        failure_message=message, order_index=index,
                    ))
                for index, material in enumerate(item.get("materials", [])):
                    session.add(MaterialRequirementRecord(
                        service_version_id=version.id, code=material["code"], name=material["name"],
                        required=material.get("required", True), condition_json=material.get("condition"),
                        accepted_types=["application/pdf", "image/jpeg", "image/png"], order_index=index,
                    ))
                for step in item.get("steps", []):
                    session.add(ProcessStepRecord(
                        service_version_id=version.id, order_index=step["order"],
                        code=step["code"], title=step["title"], actor=step["actor"],
                        description=step["description"], expected_duration=step["expected_duration"],
                    ))
                session.add(PolicySourceRecord(
                    service_version_id=version.id, title="本地演示业务说明",
                    reference=f"demo://services/{item['code']}",
                ))

    async def get_account_by_username(self, username: str) -> AccountRecord | None:
        async with self.sessions() as session:
            return await session.scalar(
                select(AccountRecord).where(AccountRecord.username == username.strip().lower())
            )

    async def get_account_record(self, account_id: UUID) -> AccountRecord | None:
        async with self.sessions() as session:
            return await session.get(AccountRecord, account_id)

    async def get_account_view(self, account_id: UUID) -> dict[str, Any]:
        async with self.sessions() as session:
            record = await session.get(AccountRecord, account_id)
            if record is None:
                raise ResourceNotFound("账号")
            return account_view(record)

    async def create_account(
        self, username: str, password_hash: str, display_name: str,
        applicant_type: ApplicantType, role: Role = Role.CITIZEN,
        department_id: UUID | None = None,
    ) -> AccountRecord:
        try:
            async with self._transaction() as session:
                record = AccountRecord(
                    username=username.strip().lower(), password_hash=password_hash,
                    display_name=display_name.strip(), role=role.value,
                    applicant_type=applicant_type.value if role is Role.CITIZEN else None,
                    active=True, token_version=0, department_id=department_id,
                    profile_json={"demo": True},
                )
                session.add(record)
                await session.flush()
                await self._audit(session, record.id, "account.created", "account", record.id, {"role": role.value})
                return record
        except IntegrityError as exc:
            raise ConflictError("用户名已存在", "username_exists") from exc

    async def save_refresh_token(
        self, account_id: UUID, token: str, expires_at: datetime
    ) -> None:
        async with self._transaction() as session:
            session.add(RefreshTokenRecord(
                account_id=account_id, token_hash=hash_token(token), expires_at=expires_at,
            ))

    async def save_refresh_token_if_current(
        self, account_id: UUID, expected_token_version: int,
        token: str, expires_at: datetime,
    ) -> None:
        async with self._transaction() as session:
            account = await session.get(AccountRecord, account_id, with_for_update=True)
            if (
                account is None
                or not account.active
                or account.token_version != expected_token_version
            ):
                raise AuthenticationRequired("账号状态已变化，请重新登录")
            session.add(RefreshTokenRecord(
                account_id=account_id,
                token_hash=hash_token(token),
                expires_at=expires_at,
            ))

    async def consume_refresh_token(self, token: str) -> AccountRecord | None:
        now = datetime.now(timezone.utc)
        async with self._transaction() as session:
            record = await session.scalar(
                select(RefreshTokenRecord).where(
                    RefreshTokenRecord.token_hash == hash_token(token),
                    RefreshTokenRecord.revoked_at.is_(None),
                    RefreshTokenRecord.expires_at > now,
                ).with_for_update()
            )
            if record is None:
                return None
            record.revoked_at = now
            return await session.get(AccountRecord, record.account_id)

    async def revoke_refresh_token(self, token: str) -> None:
        async with self._transaction() as session:
            await session.execute(
                update(RefreshTokenRecord)
                .where(RefreshTokenRecord.token_hash == hash_token(token), RefreshTokenRecord.revoked_at.is_(None))
                .values(revoked_at=datetime.now(timezone.utc))
            )

    async def set_account_active(self, actor_id: UUID, account_id: UUID, active: bool) -> dict[str, Any]:
        async with self._transaction() as session:
            record = await session.get(AccountRecord, account_id, with_for_update=True)
            if record is None:
                raise ResourceNotFound("账号")
            if record.role == Role.ADMIN.value and not active:
                admin_count = await session.scalar(
                    select(func.count()).select_from(AccountRecord).where(
                        AccountRecord.role == Role.ADMIN.value, AccountRecord.active.is_(True)
                    )
                )
                if admin_count == 1:
                    raise ConflictError("不能冻结最后一个有效管理员")
            record.active = active
            record.token_version += 1
            await session.execute(
                update(RefreshTokenRecord)
                .where(RefreshTokenRecord.account_id == account_id, RefreshTokenRecord.revoked_at.is_(None))
                .values(revoked_at=datetime.now(timezone.utc))
            )
            await self._audit(session, actor_id, "account.status_changed", "account", account_id, {"active": active})
            await session.flush()
            return account_view(record)

    async def list_services(self, query: str | None = None, include_all: bool = False) -> list[dict[str, Any]]:
        async with self.sessions() as session:
            statement = (
                select(GovernmentServiceRecord, ServiceVersionRecord)
                .join(ServiceVersionRecord, GovernmentServiceRecord.current_version_id == ServiceVersionRecord.id)
                .order_by(GovernmentServiceRecord.code)
            )
            if not include_all:
                statement = statement.where(GovernmentServiceRecord.status == ServiceStatus.PUBLISHED.value)
            if query:
                normalized = query.strip()
                if any(term in normalized for term in ("劳动合同", "合同备案")):
                    terms = ["劳动合同"]
                elif "企业" in normalized and any(term in normalized for term in ("社保", "社会保险")):
                    terms = ["企业社会保险"]
                elif any(term in normalized for term in ("个体户", "个体工商户", "个体注册")):
                    terms = ["个体工商户"]
                elif "社保" in normalized:
                    terms = ["社会保障", "社会保险"]
                elif "身份证" in normalized:
                    terms = ["身份证"]
                elif "公积金" in normalized:
                    terms = ["公积金"]
                else:
                    terms = [normalized]
                predicates = []
                for term in terms:
                    like = f"%{term}%"
                    predicates.extend((ServiceVersionRecord.title.ilike(like), ServiceVersionRecord.summary.ilike(like), GovernmentServiceRecord.code.ilike(like)))
                statement = statement.where(or_(*predicates))
            rows = (await session.execute(statement)).all()
            return [self._service_summary(service, version) for service, version in rows]

    async def get_service_bundle(self, service_id: UUID, include_all: bool = False) -> dict[str, Any]:
        async with self.sessions() as session:
            service = await session.get(GovernmentServiceRecord, service_id)
            if service is None or (not include_all and service.status != ServiceStatus.PUBLISHED.value):
                raise ResourceNotFound("事项")
            if service.current_version_id is None:
                raise ResourceNotFound("事项版本")
            version = await session.get(ServiceVersionRecord, service.current_version_id)
            if version is None:
                raise ResourceNotFound("事项版本")
            rules = list((await session.scalars(select(EligibilityRuleRecord).where(EligibilityRuleRecord.service_version_id == version.id).order_by(EligibilityRuleRecord.order_index))).all())
            materials = list((await session.scalars(select(MaterialRequirementRecord).where(MaterialRequirementRecord.service_version_id == version.id).order_by(MaterialRequirementRecord.order_index))).all())
            steps = list((await session.scalars(select(ProcessStepRecord).where(ProcessStepRecord.service_version_id == version.id).order_by(ProcessStepRecord.order_index))).all())
            sources = list((await session.scalars(select(PolicySourceRecord).where(PolicySourceRecord.service_version_id == version.id))).all())
            window_rows = (
                await session.execute(
                    select(ServiceWindowLinkRecord, ServiceWindowRecord)
                    .join(
                        ServiceWindowRecord,
                        ServiceWindowRecord.id == ServiceWindowLinkRecord.window_id,
                    )
                    .where(
                        ServiceWindowLinkRecord.service_id == service.id,
                        ServiceWindowLinkRecord.active.is_(True),
                        ServiceWindowRecord.active.is_(True),
                    )
                    .order_by(
                        ServiceWindowLinkRecord.priority,
                        ServiceWindowRecord.code,
                    )
                )
            ).all()
            return {
                **self._service_summary(service, version),
                "version": version.version,
                "version_id": version.id,
                "form_schema": version.form_schema,
                "eligibility_rules": [{"rule": item.rule_json, "failure_message": item.failure_message} for item in rules],
                "materials": [self._material_dict(item) for item in materials],
                "process_steps": [{"order": item.order_index, "code": item.code, "title": item.title, "actor": item.actor, "description": item.description, "expected_duration": item.expected_duration} for item in steps],
                "policy_sources": [{"title": item.title, "reference": item.reference} for item in sources],
                "windows": [
                    self._navigation_window_dict(window, link.priority)
                    for link, window in window_rows
                ],
                "notice": "全部事项、条件、窗口和政策来源均为本地演示数据。",
            }

    async def get_navigation_options(self, service_id: UUID) -> dict[str, Any]:
        """Return only authoritative, active catalog rows; never user location."""

        async with self.sessions() as session:
            row = (
                await session.execute(
                    select(GovernmentServiceRecord, ServiceVersionRecord)
                    .join(
                        ServiceVersionRecord,
                        GovernmentServiceRecord.current_version_id
                        == ServiceVersionRecord.id,
                    )
                    .where(
                        GovernmentServiceRecord.id == service_id,
                        GovernmentServiceRecord.status
                        == ServiceStatus.PUBLISHED.value,
                    )
                )
            ).first()
            if row is None:
                raise ResourceNotFound("事项")
            service, version = row
            window_rows = (
                await session.execute(
                    select(ServiceWindowLinkRecord, ServiceWindowRecord)
                    .join(
                        ServiceWindowRecord,
                        ServiceWindowRecord.id == ServiceWindowLinkRecord.window_id,
                    )
                    .where(
                        ServiceWindowLinkRecord.service_id == service.id,
                        ServiceWindowLinkRecord.active.is_(True),
                        ServiceWindowRecord.active.is_(True),
                    )
                    .order_by(
                        ServiceWindowLinkRecord.priority,
                        ServiceWindowRecord.code,
                    )
                )
            ).all()
            windows = [
                self._navigation_window_dict(window, link.priority)
                for link, window in window_rows
            ]
            demo_only, notice = self._navigation_catalog_notice(windows)
            return {
                "service": {
                    "id": service.id,
                    "code": service.code,
                    "name": version.title,
                    "handling_mode": service.handling_mode,
                    "online_status": service.online_status,
                    "status_reason": service.status_reason,
                    "status_updated_at": service.status_updated_at,
                },
                "windows": windows,
                "active_location_count": len(windows),
                "demo_only": demo_only,
                "notice": notice,
            }

    @staticmethod
    def _navigation_catalog_notice(
        windows: list[dict[str, Any]],
    ) -> tuple[bool, str]:
        """Keep the demo warning until every returned location is verified."""

        if not windows:
            return False, "当前没有已启用的线下网点。"
        has_demo = any(item.get("data_mode") != "VERIFIED" for item in windows)
        if has_demo:
            if all(item.get("data_mode") == "DEMO" for item in windows):
                return True, "当前均为演示网点，不可用于真实导航。"
            return True, "当前结果包含演示网点；演示网点不可用于真实导航。"
        return False, "网点来自管理员核验目录；出发前请再次确认开放时间。"

    async def get_material_entities(self, service_id: UUID) -> tuple[dict[str, Any], list[MaterialRequirement]]:
        bundle = await self.get_service_bundle(service_id)
        return bundle, [
            MaterialRequirement(
                id=item["id"], service_version_id=bundle["version_id"], code=item["code"],
                name=item["name"], required=item["required"], condition=item["condition"],
                accepted_types=tuple(item["accepted_types"]),
            )
            for item in bundle["materials"]
        ]

    async def create_department(self, actor_id: UUID, code: str, name: str) -> dict[str, Any]:
        try:
            async with self._transaction() as session:
                record = DepartmentRecord(code=code.strip().upper(), name=name.strip(), active=True)
                session.add(record); await session.flush()
                await self._audit(session, actor_id, "department.created", "department", record.id, {"code": record.code})
                return self._department_dict(record)
        except IntegrityError as exc:
            raise ConflictError("部门编码已存在") from exc

    async def list_departments(self) -> list[dict[str, Any]]:
        async with self.sessions() as session:
            return [self._department_dict(item) for item in (await session.scalars(select(DepartmentRecord).order_by(DepartmentRecord.code))).all()]

    async def create_window(self, actor_id: UUID, values: dict[str, Any]) -> dict[str, Any]:
        try:
            async with self._transaction() as session:
                if await session.get(DepartmentRecord, values["department_id"]) is None:
                    raise ResourceNotFound("部门")
                record = ServiceWindowRecord(**values, active=True)
                session.add(record); await session.flush()
                await self._audit(session, actor_id, "window.created", "window", record.id, {"code": record.code})
                return self._window_dict(record)
        except IntegrityError as exc:
            raise ConflictError("窗口编码已存在") from exc

    async def create_service(self, actor_id: UUID, values: dict[str, Any]) -> dict[str, Any]:
        try:
            async with self._transaction() as session:
                if await session.get(DepartmentRecord, values["department_id"]) is None:
                    raise ResourceNotFound("部门")
                if values.get("window_id"):
                    window = await session.get(ServiceWindowRecord, values["window_id"])
                    if window is None or window.department_id != values["department_id"]:
                        raise ResourceNotFound("部门窗口")
                service = GovernmentServiceRecord(
                    code=values["code"], department_id=values["department_id"],
                    window_id=values.get("window_id"),
                    applicant_type=values["applicant_type"], status=ServiceStatus.DRAFT.value,
                    handling_mode="UNKNOWN", online_status="UNKNOWN",
                )
                session.add(service); await session.flush()
                if values.get("window_id"):
                    session.add(
                        ServiceWindowLinkRecord(
                            service_id=service.id,
                            window_id=values["window_id"],
                            priority=0,
                            active=True,
                        )
                    )
                version = await self._insert_version(session, service.id, 1, values)
                service.current_version_id = version.id
                await self._audit(session, actor_id, "service.created", "service", service.id, {"version": 1})
                await session.flush()
                return self._service_summary(service, version)
        except IntegrityError as exc:
            raise ConflictError("事项编码已存在") from exc

    async def create_service_version(self, actor_id: UUID, service_id: UUID, values: dict[str, Any]) -> dict[str, Any]:
        async with self._transaction() as session:
            service = await session.get(GovernmentServiceRecord, service_id, with_for_update=True)
            if service is None:
                raise ResourceNotFound("事项")
            next_version = (await session.scalar(select(func.max(ServiceVersionRecord.version)).where(ServiceVersionRecord.service_id == service_id)) or 0) + 1
            version = await self._insert_version(session, service_id, next_version, values)
            await self._audit(session, actor_id, "service.version_created", "service", service_id, {"version": next_version})
            return {"id": version.id, "service_id": service_id, "version": next_version, "immutable": False}

    async def transition_service(self, actor_id: UUID, service_id: UUID, target: ServiceStatus, version_id: UUID | None) -> dict[str, Any]:
        async with self._transaction() as session:
            service = await session.get(GovernmentServiceRecord, service_id, with_for_update=True)
            if service is None:
                raise ResourceNotFound("事项")
            current = ServiceStatus(service.status)
            try:
                self._service_states.require(current, target)
            except DomainRuleViolation as exc:
                raise ConflictError(str(exc), "invalid_service_transition") from exc
            if target is ServiceStatus.PUBLISHED:
                selected = version_id or service.current_version_id
                version = await session.get(ServiceVersionRecord, selected) if selected else None
                if version is None or version.service_id != service.id:
                    raise ConflictError("发布版本不属于该事项")
                version.immutable = True
                version.published_at = datetime.now(timezone.utc)
                service.current_version_id = version.id
            service.status = target.value
            await self._audit(session, actor_id, "service.lifecycle", "service", service.id, {"from": current.value, "to": target.value})
            await session.flush()
            version = await session.get(ServiceVersionRecord, service.current_version_id) if service.current_version_id else None
            return self._service_summary(service, version) if version else {"id": service.id, "status": service.status}

    async def create_application(self, actor_id: UUID, service_id: UUID, form_data: dict[str, Any]) -> dict[str, Any]:
        async with self._transaction() as session:
            service = await session.get(GovernmentServiceRecord, service_id)
            if service is None or service.status != ServiceStatus.PUBLISHED.value or service.current_version_id is None:
                raise ResourceNotFound("已发布事项")
            account = await session.get(AccountRecord, actor_id)
            if account is None or account.role != Role.CITIZEN.value:
                raise PermissionDenied("只有群众账号可以创建办件")
            if account.applicant_type != service.applicant_type:
                raise PermissionDenied("账号申请人类型与事项不匹配")
            record = ApplicationRecord(
                applicant_id=actor_id, service_id=service.id, service_version_id=service.current_version_id,
                status=ApplicationStatus.DRAFT.value, form_data=form_data, version=1,
            )
            session.add(record); await session.flush()
            await self._event(session, record, actor_id, "application.created", None, ApplicationStatus.DRAFT, {})
            await self._audit(session, actor_id, "application.created", "application", record.id, {"service_id": str(service.id)})
            return application_view(record)

    async def list_applications(self, principal_id: UUID, role: Role, department_id: UUID | None) -> list[dict[str, Any]]:
        async with self.sessions() as session:
            statement = select(ApplicationRecord).order_by(ApplicationRecord.created_at.desc())
            if role is Role.CITIZEN:
                statement = statement.where(ApplicationRecord.applicant_id == principal_id)
            elif role is Role.STAFF:
                statement = (
                    statement.join(
                        ReviewTaskRecord,
                        ReviewTaskRecord.application_id == ApplicationRecord.id,
                    )
                    .where(
                        ApplicationRecord.status.not_in(
                            [
                                ApplicationStatus.DRAFT.value,
                                ApplicationStatus.DISCARDED.value,
                                ApplicationStatus.WITHDRAWN.value,
                            ]
                        ),
                        ReviewTaskRecord.department_id == department_id,
                        ReviewTaskRecord.status.in_(["PENDING", "CLAIMED"]),
                        or_(
                            ReviewTaskRecord.assignee_id.is_(None),
                            ReviewTaskRecord.assignee_id == principal_id,
                        ),
                    )
                    .distinct()
                )
            return [application_view(item) for item in (await session.scalars(statement)).all()]

    async def get_application_authorized(self, application_id: UUID, actor_id: UUID, role: Role, department_id: UUID | None = None) -> ApplicationRecord:
        async with self.sessions() as session:
            record = await session.get(ApplicationRecord, application_id)
            await self._require_application_access(session, record, actor_id, role, department_id)
            return record  # type: ignore[return-value]

    async def get_application_view_authorized(
        self, application_id: UUID, actor_id: UUID, role: Role,
        department_id: UUID | None = None,
    ) -> dict[str, Any]:
        async with self.sessions() as session:
            record = await session.get(ApplicationRecord, application_id)
            await self._require_application_access(
                session, record, actor_id, role, department_id
            )
            return application_view(record)  # type: ignore[arg-type]

    async def get_application_case_authorized(
        self, application_id: UUID, actor_id: UUID, role: Role,
        department_id: UUID | None = None,
    ) -> dict[str, Any]:
        async with self.sessions() as session:
            record = await session.get(ApplicationRecord, application_id)
            await self._require_application_access(
                session, record, actor_id, role, department_id
            )
            # A submitted application is pinned to an immutable version. Its
            # authorized status lookup must remain available even when the
            # public catalogue item is later suspended or retired.
            service = await session.get(GovernmentServiceRecord, record.service_id)
            version = await session.get(
                ServiceVersionRecord, record.service_version_id
            )
            if service is None or version is None:
                raise ResourceNotFound("办件关联事项版本")
            return {
                "id": record.id,
                "service_id": record.service_id,
                "service_version_id": record.service_version_id,
                "service_code": service.code,
                "service_title": version.title,
                "service_summary": version.summary,
                "external_item_id": service.external_item_id,
                "status": record.status,
            }

    async def update_application_form(self, application_id: UUID, actor_id: UUID, data: dict[str, Any], expected_version: int) -> dict[str, Any]:
        async with self._transaction() as session:
            result = await session.execute(
                update(ApplicationRecord).where(
                    ApplicationRecord.id == application_id, ApplicationRecord.applicant_id == actor_id,
                    ApplicationRecord.status.in_([ApplicationStatus.DRAFT.value, ApplicationStatus.NEEDS_SUPPLEMENT.value]),
                    ApplicationRecord.version == expected_version,
                ).values(form_data=data, version=ApplicationRecord.version + 1, updated_at=datetime.now(timezone.utc)).returning(ApplicationRecord)
            )
            record = result.scalar_one_or_none()
            if record is None:
                existing = await session.get(ApplicationRecord, application_id)
                if existing is None:
                    raise ResourceNotFound("办件")
                if existing.applicant_id != actor_id:
                    raise PermissionDenied()
                raise ConflictError("办件版本或状态已变化，请刷新后重试", "optimistic_lock_conflict")
            await self._event(session, record, actor_id, "application.form_updated", ApplicationStatus(record.status), ApplicationStatus(record.status), {})
            return application_view(record)

    async def add_material(
        self, application_id: UUID, actor_id: UUID, requirement_code: str, original_name: str,
        object_key: str, content_type: str, size_bytes: int, digest: str,
    ) -> dict[str, Any]:
        async with self._transaction() as session:
            app = await session.get(ApplicationRecord, application_id, with_for_update=True)
            if app is None:
                raise ResourceNotFound("办件")
            if app.applicant_id != actor_id:
                raise PermissionDenied()
            if app.status not in {ApplicationStatus.DRAFT.value, ApplicationStatus.NEEDS_SUPPLEMENT.value}:
                raise ConflictError("当前办件状态不允许上传材料")
            record = ApplicationMaterialRecord(
                application_id=application_id, requirement_code=requirement_code,
                original_name=original_name, object_key=object_key, content_type=content_type,
                size_bytes=size_bytes, sha256=digest, scan_status="NOT_SCANNED_DEMO",
            )
            session.add(record); app.version += 1; await session.flush()
            await self._event(session, app, actor_id, "application.material_uploaded", ApplicationStatus(app.status), ApplicationStatus(app.status), {"requirement_code": requirement_code, "sha256": digest})
            return {"id": record.id, "requirement_code": requirement_code, "original_name": original_name, "content_type": content_type, "size_bytes": size_bytes, "sha256": digest, "scan_status": record.scan_status, "application_version": app.version, "demo_data": True}

    async def preflight_material_upload(
        self, application_id: UUID, actor_id: UUID, requirement_code: str,
        content_type: str,
    ) -> None:
        async with self.sessions() as session:
            app = await session.get(ApplicationRecord, application_id)
            if app is None:
                raise ResourceNotFound("办件")
            if app.applicant_id != actor_id:
                raise PermissionDenied()
            if app.status not in {ApplicationStatus.DRAFT.value, ApplicationStatus.NEEDS_SUPPLEMENT.value}:
                raise ConflictError("当前办件状态不允许上传材料")
            requirement = await session.scalar(
                select(MaterialRequirementRecord).where(
                    MaterialRequirementRecord.service_version_id == app.service_version_id,
                    MaterialRequirementRecord.code == requirement_code,
                )
            )
            if requirement is None:
                raise ResourceNotFound("事项材料要求")
            if content_type not in requirement.accepted_types:
                raise BusinessValidationError(
                    "该材料要求不接受此文件类型",
                    {"accepted_types": list(requirement.accepted_types)},
                )

    async def get_material_authorized(
        self,
        application_id: UUID,
        material_id: UUID,
        actor_id: UUID,
        role: Role,
        department_id: UUID | None,
    ) -> dict[str, Any]:
        async with self.sessions() as session:
            app = await session.get(ApplicationRecord, application_id)
            await self._require_application_access(session, app, actor_id, role, department_id)
            material = await session.get(ApplicationMaterialRecord, material_id)
            if material is None or material.application_id != application_id:
                raise ResourceNotFound("办件材料")
            return {
                "id": material.id,
                "object_key": material.object_key,
                "original_name": material.original_name,
                "content_type": material.content_type,
                "size_bytes": material.size_bytes,
                "sha256": material.sha256,
            }

    async def application_submission_context(self, application_id: UUID, actor_id: UUID) -> tuple[Application, dict[str, Any], set[str], list[MaterialRequirement], bool]:
        async with self.sessions() as session:
            app = await session.get(ApplicationRecord, application_id)
            if app is None:
                raise ResourceNotFound("办件")
            if app.applicant_id != actor_id:
                raise PermissionDenied()
            version = await session.get(ServiceVersionRecord, app.service_version_id)
            materials = set((await session.scalars(select(ApplicationMaterialRecord.requirement_code).where(ApplicationMaterialRecord.application_id == app.id))).all())
            requirements = list((await session.scalars(select(MaterialRequirementRecord).where(MaterialRequirementRecord.service_version_id == app.service_version_id))).all())
            verification_passed = bool(await session.scalar(select(func.count()).select_from(VerificationSessionRecord).where(VerificationSessionRecord.application_id == app.id, VerificationSessionRecord.status == "PASSED")))
            rules = list((await session.scalars(select(EligibilityRuleRecord).where(EligibilityRuleRecord.service_version_id == app.service_version_id).order_by(EligibilityRuleRecord.order_index))).all())
            appointment_booked = bool(await session.scalar(select(func.count()).select_from(AppointmentRecord).where(AppointmentRecord.account_id == actor_id, AppointmentRecord.service_id == app.service_id, AppointmentRecord.status == "BOOKED", AppointmentRecord.slot_start > datetime.now(timezone.utc))))
            return _application(app), ({
                "form_schema": version.form_schema if version else {},
                "requires_verification": version.requires_verification if version else False,
                "requires_appointment": version.requires_appointment if version else False,
                "fee_cents": version.fee_cents if version else 0,
                "eligibility_rules": [(item.rule_json, item.failure_message) for item in rules],
                "appointment_booked": appointment_booked,
            }), materials, [MaterialRequirement(id=item.id, service_version_id=item.service_version_id, code=item.code, name=item.name, required=item.required, condition=item.condition_json, accepted_types=tuple(item.accepted_types)) for item in requirements], verification_passed

    async def submit_application(self, application_id: UUID, actor_id: UUID, expected_version: int) -> dict[str, Any]:
        async with self._transaction() as session:
            app = await session.get(ApplicationRecord, application_id, with_for_update=True)
            if app is None:
                raise ResourceNotFound("办件")
            if app.applicant_id != actor_id:
                raise PermissionDenied()
            if app.version != expected_version:
                raise ConflictError("办件版本已变化，请刷新后重试", "optimistic_lock_conflict")
            service = await session.get(
                GovernmentServiceRecord, app.service_id, with_for_update=True
            )
            if service is None or service.status != ServiceStatus.PUBLISHED.value:
                raise ConflictError(
                    "事项已暂停、终止或尚未发布，当前不能提交办件",
                    "service_not_accepting_applications",
                )
            current = ApplicationStatus(app.status)
            try:
                self._application_states.require(current, ApplicationStatus.SUBMITTED)
            except DomainRuleViolation as exc:
                raise ConflictError(str(exc), "invalid_application_transition") from exc
            app.status = ApplicationStatus.SUBMITTED.value; app.version += 1; app.submitted_at = datetime.now(timezone.utc)
            session.add(ReviewTaskRecord(application_id=app.id, department_id=service.department_id, status="PENDING"))  # type: ignore[union-attr]
            await self._event(session, app, actor_id, "application.submitted", current, ApplicationStatus.SUBMITTED, {})
            await self._audit(session, actor_id, "application.submitted", "application", app.id, {})
            # Loading the service above triggers an autoflush. ``updated_at`` uses
            # a SQL-side on-update expression, so SQLAlchemy expires that one
            # attribute. Refresh explicitly while we are still in the async
            # greenlet instead of letting response serialization attempt lazy IO.
            await session.flush()
            await session.refresh(app)
            return application_view(app)

    async def transition_application(
        self, application_id: UUID, actor_id: UUID, role: Role, target: ApplicationStatus,
        expected_version: int, comment: str | None = None, require_assignee: bool = False,
    ) -> dict[str, Any]:
        async with self._transaction() as session:
            app = await session.get(ApplicationRecord, application_id, with_for_update=True)
            if app is None:
                raise ResourceNotFound("办件")
            if app.version != expected_version:
                raise ConflictError("办件版本已变化，请刷新后重试", "optimistic_lock_conflict")
            if role is Role.CITIZEN and app.applicant_id != actor_id:
                raise PermissionDenied()
            task = await session.scalar(select(ReviewTaskRecord).where(ReviewTaskRecord.application_id == application_id).order_by(ReviewTaskRecord.created_at.desc()).limit(1))
            if role is Role.STAFF and (task is None or (require_assignee and task.assignee_id != actor_id)):
                raise PermissionDenied("请先认领该审核任务")
            current = ApplicationStatus(app.status)
            try:
                self._application_states.require(current, target)
            except DomainRuleViolation as exc:
                raise ConflictError(str(exc), "invalid_application_transition") from exc
            app.status = target.value; app.version += 1
            if target is ApplicationStatus.COMPLETED:
                app.completed_at = datetime.now(timezone.utc)
            if target is ApplicationStatus.WITHDRAWN:
                # A citizen withdrawal and task closure are one atomic state
                # change. Closing every active task also repairs any duplicate
                # legacy rows and prevents a stale task from being claimed.
                await session.execute(
                    update(ReviewTaskRecord)
                    .where(
                        ReviewTaskRecord.application_id == application_id,
                        ReviewTaskRecord.status.in_(["PENDING", "CLAIMED"]),
                    )
                    .values(
                        status="CANCELLED",
                        decision=ApplicationStatus.WITHDRAWN.value,
                        comment=comment,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                await session.execute(
                    update(PaymentOrderRecord)
                    .where(
                        PaymentOrderRecord.application_id == application_id,
                        PaymentOrderRecord.status.in_(
                            ["CREATED", "PENDING", "FAILED"]
                        ),
                    )
                    .values(
                        status=PaymentStatus.CANCELLED.value,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
            elif task is not None and target in {ApplicationStatus.REJECTED, ApplicationStatus.AWAITING_PAYMENT, ApplicationStatus.PROCESSING, ApplicationStatus.COMPLETED, ApplicationStatus.NEEDS_SUPPLEMENT}:
                task.decision = target.value; task.comment = comment
                task.status = "COMPLETED"
                if target is ApplicationStatus.PROCESSING:
                    session.add(ReviewTaskRecord(
                        application_id=app.id,
                        department_id=task.department_id,
                        status="PENDING",
                    ))
            await self._event(session, app, actor_id, f"application.{target.value.lower()}", current, target, {"comment": comment} if comment else {})
            await self._audit(session, actor_id, "application.transition", "application", app.id, {"from": current.value, "to": target.value})
            # Bulk task/payment closure above can autoflush the application.
            # ``updated_at`` uses a SQL-side on-update expression and becomes
            # expired; refresh it inside the async greenlet before mapping.
            await session.flush()
            await session.refresh(app)
            return application_view(app)

    async def list_timeline(self, application_id: UUID, actor_id: UUID, role: Role, department_id: UUID | None) -> list[dict[str, Any]]:
        async with self.sessions() as session:
            app = await session.get(ApplicationRecord, application_id)
            await self._require_application_access(session, app, actor_id, role, department_id)
            events = (await session.scalars(select(ApplicationEventRecord).where(ApplicationEventRecord.application_id == application_id).order_by(ApplicationEventRecord.created_at))).all()
            return [{"id": item.id, "event_type": item.event_type, "from_status": item.from_status, "to_status": item.to_status, "detail": redact_sensitive(item.detail_json), "created_at": item.created_at} for item in events]

    async def list_staff_tasks(self, account_id: UUID, department_id: UUID | None) -> list[dict[str, Any]]:
        if department_id is None:
            return []
        async with self.sessions() as session:
            rows = (await session.execute(
                select(ReviewTaskRecord, ApplicationRecord).join(ApplicationRecord, ReviewTaskRecord.application_id == ApplicationRecord.id)
                .where(
                    ReviewTaskRecord.department_id == department_id,
                    ReviewTaskRecord.status.in_(["PENDING", "CLAIMED"]),
                    ApplicationRecord.status.in_(
                        _REVIEW_TASK_APPLICATION_STATUSES
                    ),
                    or_(ReviewTaskRecord.assignee_id.is_(None), ReviewTaskRecord.assignee_id == account_id),
                )
                .order_by(ReviewTaskRecord.created_at)
            )).all()
            return [{"id": task.id, "application": application_view(app), "status": task.status, "assignee_id": task.assignee_id, "decision": task.decision, "comment": task.comment} for task, app in rows]

    async def get_review_task_department(self, task_id: UUID) -> UUID:
        async with self.sessions() as session:
            task = await session.get(ReviewTaskRecord, task_id)
            if task is None:
                raise ResourceNotFound("审核任务")
            return task.department_id

    async def get_application_review_department(
        self, application_id: UUID
    ) -> UUID:
        async with self.sessions() as session:
            department_id = await session.scalar(
                select(ReviewTaskRecord.department_id)
                .where(
                    ReviewTaskRecord.application_id == application_id,
                    ReviewTaskRecord.status.in_(["PENDING", "CLAIMED"]),
                )
                .order_by(ReviewTaskRecord.created_at.desc())
                .limit(1)
            )
            if department_id is None:
                raise ResourceNotFound("审核任务")
            return department_id

    async def claim_task(self, task_id: UUID, actor_id: UUID, department_id: UUID | None) -> dict[str, Any]:
        if department_id is None:
            raise PermissionDenied("工作人员未分配部门")
        async with self._transaction() as session:
            snapshot = await session.get(ReviewTaskRecord, task_id)
            if snapshot is None:
                raise ResourceNotFound("审核任务")
            if snapshot.department_id != department_id:
                raise PermissionDenied("只能认领所属部门审核任务")

            # Lock in the same aggregate order as withdrawal: application first,
            # then task. Re-read the task after both locks so a concurrent
            # withdrawal can never leave a claimable zombie row.
            app = await session.get(
                ApplicationRecord, snapshot.application_id, with_for_update=True
            )
            task = await session.get(
                ReviewTaskRecord,
                task_id,
                with_for_update=True,
                populate_existing=True,
            )
            if app is None or task is None:
                raise ResourceNotFound("审核任务")
            if app.status not in _REVIEW_TASK_APPLICATION_STATUSES:
                raise ConflictError(
                    "办件已不在可审核状态",
                    "application_not_reviewable",
                )
            if task.department_id != department_id:
                raise PermissionDenied("只能认领所属部门审核任务")
            if task.status == "CLAIMED" and task.assignee_id == actor_id:
                return {
                    "id": task.id,
                    "application_id": task.application_id,
                    "status": task.status,
                    "assignee_id": task.assignee_id,
                }
            if task.status != "PENDING" or task.assignee_id is not None:
                raise ConflictError("任务已被其他工作人员认领", "task_already_claimed")
            task.assignee_id = actor_id
            task.status = "CLAIMED"
            task.updated_at = datetime.now(timezone.utc)
            if app.status == ApplicationStatus.SUBMITTED.value:
                app.status = ApplicationStatus.IN_REVIEW.value; app.version += 1
                await self._event(session, app, actor_id, "application.review_started", ApplicationStatus.SUBMITTED, ApplicationStatus.IN_REVIEW, {})
            await self._audit(session, actor_id, "review_task.claimed", "review_task", task.id, {})
            return {"id": task.id, "application_id": task.application_id, "status": task.status, "assignee_id": task.assignee_id}

    async def create_feedback(self, account_id: UUID, session_id: UUID, rating: int, comment: str | None) -> dict[str, Any]:
        async with self._transaction() as session:
            chat = await session.get(ChatSession, session_id)
            if chat is None or chat.owner_account_id != account_id:
                raise ResourceNotFound("咨询会话")
            record = ConsultationFeedbackRecord(session_id=session_id, account_id=account_id, rating=rating, comment=comment)
            session.add(record); await session.flush()
            return {"id": record.id, "session_id": session_id, "rating": rating, "comment": comment}

    async def list_consultations(self, account_id: UUID) -> list[dict[str, Any]]:
        async with self.sessions() as session:
            sessions = (
                await session.scalars(
                    select(ChatSession)
                    .where(ChatSession.owner_account_id == account_id)
                    .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
                )
            ).all()
            result = []
            for chat in sessions:
                count = await session.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.session_id == chat.id))
                result.append({"id": chat.id, "created_at": chat.created_at, "updated_at": chat.updated_at, "message_count": count or 0})
            return result

    async def create_handoff(self, account_id: UUID, session_id: UUID, subject: str, department_id: UUID | None) -> dict[str, Any]:
        async with self._transaction() as session:
            chat = await session.get(ChatSession, session_id)
            if chat is None or chat.owner_account_id != account_id:
                raise ResourceNotFound("咨询会话")
            record = HandoffTicketRecord(session_id=session_id, requester_id=account_id, department_id=department_id, status="QUEUED", subject=subject)
            session.add(record); await session.flush()
            await self._audit(session, account_id, "handoff.created", "handoff", record.id, {})
            return self._handoff_dict(record)

    async def list_handoffs(self, actor_id: UUID, role: Role, department_id: UUID | None) -> list[dict[str, Any]]:
        async with self.sessions() as session:
            statement = select(HandoffTicketRecord).order_by(HandoffTicketRecord.created_at.desc())
            if role is Role.CITIZEN:
                statement = statement.where(HandoffTicketRecord.requester_id == actor_id)
            elif role is Role.STAFF:
                statement = statement.where(or_(HandoffTicketRecord.department_id == department_id, HandoffTicketRecord.department_id.is_(None)))
            return [self._handoff_dict(item) for item in (await session.scalars(statement)).all()]

    async def add_handoff_message(self, actor_id: UUID, role: Role, department_id: UUID | None, ticket_id: UUID, content: str) -> dict[str, Any]:
        async with self._transaction() as session:
            ticket = await session.get(HandoffTicketRecord, ticket_id, with_for_update=True)
            if ticket is None:
                raise ResourceNotFound("人工咨询")
            if ticket.status not in {
                HandoffStatus.QUEUED.value,
                HandoffStatus.CLAIMED.value,
                HandoffStatus.IN_PROGRESS.value,
            }:
                raise ConflictError("人工咨询已结束，不能继续发送消息", "handoff_terminal")
            if role is Role.CITIZEN and ticket.requester_id != actor_id:
                raise PermissionDenied()
            if role is Role.STAFF:
                try:
                    self._handoff_access.require_staff_access(
                        str(actor_id), str(department_id) if department_id else None,
                        str(ticket.department_id) if ticket.department_id else None,
                        str(ticket.assignee_id) if ticket.assignee_id else None,
                        claiming=True,
                    )
                except DomainRuleViolation as exc:
                    raise PermissionDenied(str(exc)) from exc
                if ticket.assignee_id is None:
                    self._handoff_states.require(
                        HandoffStatus(ticket.status), HandoffStatus.CLAIMED
                    )
                    ticket.assignee_id = actor_id
                    ticket.department_id = department_id
                    ticket.status = HandoffStatus.CLAIMED.value
                if ticket.status == HandoffStatus.CLAIMED.value:
                    self._handoff_states.require(
                        HandoffStatus.CLAIMED, HandoffStatus.IN_PROGRESS
                    )
                    ticket.status = HandoffStatus.IN_PROGRESS.value
            message = HandoffMessageRecord(ticket_id=ticket.id, sender_id=actor_id, content=content)
            session.add(message); await session.flush()
            return {"id": message.id, "ticket_id": ticket.id, "sender_id": actor_id, "content": content, "created_at": message.created_at}

    async def list_handoff_messages(self, actor_id: UUID, role: Role, department_id: UUID | None, ticket_id: UUID) -> list[dict[str, Any]]:
        async with self.sessions() as session:
            ticket = await session.get(HandoffTicketRecord, ticket_id)
            if ticket is None or (role is Role.CITIZEN and ticket.requester_id != actor_id):
                raise ResourceNotFound("人工咨询")
            if role is Role.STAFF:
                try:
                    self._handoff_access.require_staff_access(
                        str(actor_id), str(department_id) if department_id else None,
                        str(ticket.department_id) if ticket.department_id else None,
                        str(ticket.assignee_id) if ticket.assignee_id else None,
                        claiming=False,
                    )
                except DomainRuleViolation as exc:
                    raise PermissionDenied(str(exc)) from exc
            items = (await session.scalars(select(HandoffMessageRecord).where(HandoffMessageRecord.ticket_id == ticket_id).order_by(HandoffMessageRecord.created_at))).all()
            return [{"id": item.id, "sender_id": item.sender_id, "content": item.content, "created_at": item.created_at} for item in items]

    async def resolve_handoff(self, actor_id: UUID, department_id: UUID | None, ticket_id: UUID) -> dict[str, Any]:
        async with self._transaction() as session:
            ticket = await session.get(HandoffTicketRecord, ticket_id, with_for_update=True)
            if ticket is None:
                raise ResourceNotFound("人工咨询")
            try:
                self._handoff_access.require_staff_access(
                    str(actor_id), str(department_id) if department_id else None,
                    str(ticket.department_id) if ticket.department_id else None,
                    str(ticket.assignee_id) if ticket.assignee_id else None,
                    claiming=False,
                )
            except DomainRuleViolation as exc:
                raise PermissionDenied(str(exc)) from exc
            if ticket.status not in {"CLAIMED", "IN_PROGRESS"}:
                raise ConflictError("当前人工咨询状态不能结办")
            ticket.status = "RESOLVED"
            await self._audit(session, actor_id, "handoff.resolved", "handoff", ticket.id, {})
            return self._handoff_dict(ticket)

    async def cancel_handoff(
        self, actor_id: UUID, ticket_id: UUID
    ) -> dict[str, Any]:
        async with self._transaction() as session:
            ticket = await session.get(
                HandoffTicketRecord, ticket_id, with_for_update=True
            )
            if ticket is None or ticket.requester_id != actor_id:
                raise ResourceNotFound("人工咨询")
            try:
                self._handoff_states.require(
                    HandoffStatus(ticket.status), HandoffStatus.CANCELLED
                )
            except DomainRuleViolation as exc:
                raise ConflictError(
                    str(exc), "invalid_handoff_transition"
                ) from exc
            ticket.status = HandoffStatus.CANCELLED.value
            await self._audit(
                session, actor_id, "handoff.cancelled", "handoff", ticket.id, {}
            )
            return self._handoff_dict(ticket)

    async def create_appointment(self, account_id: UUID, service_id: UUID, window_id: UUID, slot_start: datetime) -> dict[str, Any]:
        async with self._transaction() as session:
            service = await session.get(
                GovernmentServiceRecord, service_id, with_for_update=True
            )
            if service is None:
                raise ResourceNotFound("事项")
            if service.status != ServiceStatus.PUBLISHED.value:
                raise ConflictError(
                    "事项已暂停、终止或尚未发布，当前不可预约",
                    "service_not_bookable",
                )
            window = await session.get(ServiceWindowRecord, window_id, with_for_update=True)
            if (
                window is None
                or not window.active
                or service.window_id != window.id
                or window.department_id != service.department_id
            ):
                raise ResourceNotFound("有效事项窗口")
            version = await session.get(ServiceVersionRecord, service.current_version_id) if service.current_version_id else None
            if (
                version is None
                or version.service_id != service.id
                or not version.appointment_supported
            ):
                raise ConflictError("该事项不支持预约")
            if slot_start <= datetime.now(timezone.utc):
                raise ConflictError("预约时间必须晚于当前时间")
            booked = await session.scalar(select(func.count()).select_from(AppointmentRecord).where(AppointmentRecord.window_id == window_id, AppointmentRecord.slot_start == slot_start, AppointmentRecord.status == "BOOKED")) or 0
            own = await session.scalar(select(AppointmentRecord).where(AppointmentRecord.account_id == account_id, AppointmentRecord.slot_start == slot_start, AppointmentRecord.status == "BOOKED"))
            if own is not None or booked >= window.capacity_per_slot:
                raise ConflictError("该时段不可预约", "appointment_conflict")
            record = AppointmentRecord(account_id=account_id, service_id=service_id, window_id=window_id, slot_start=slot_start, status="BOOKED")
            session.add(record); await session.flush()
            await self._audit(session, account_id, "appointment.booked", "appointment", record.id, {"slot_start": slot_start.isoformat()})
            return self._appointment_dict(record)

    async def list_appointments(self, account_id: UUID) -> list[dict[str, Any]]:
        async with self.sessions() as session:
            return [self._appointment_dict(item) for item in (await session.scalars(select(AppointmentRecord).where(AppointmentRecord.account_id == account_id).order_by(AppointmentRecord.slot_start.desc()))).all()]

    async def cancel_appointment(self, account_id: UUID, appointment_id: UUID) -> dict[str, Any]:
        async with self._transaction() as session:
            record = await session.get(AppointmentRecord, appointment_id, with_for_update=True)
            if record is None or record.account_id != account_id:
                raise ResourceNotFound("预约")
            try:
                self._appointment_states.require(
                    AppointmentStatus(record.status), AppointmentStatus.CANCELLED
                )
            except DomainRuleViolation as exc:
                raise ConflictError(str(exc), "invalid_appointment_transition") from exc
            record.status = AppointmentStatus.CANCELLED.value
            await self._audit(session, account_id, "appointment.cancelled", "appointment", record.id, {})
            return self._appointment_dict(record)

    async def advance_appointment(
        self,
        actor_id: UUID,
        role: Role,
        department_id: UUID | None,
        appointment_id: UUID,
        target: AppointmentStatus,
    ) -> dict[str, Any]:
        async with self._transaction() as session:
            record = await session.get(AppointmentRecord, appointment_id, with_for_update=True)
            if record is None:
                raise ResourceNotFound("预约")
            window = await session.get(ServiceWindowRecord, record.window_id)
            if role is Role.STAFF and (
                department_id is None or window is None or window.department_id != department_id
            ):
                raise PermissionDenied("只能处理本部门窗口预约")
            if role not in {Role.STAFF, Role.ADMIN}:
                raise PermissionDenied("该功能仅向工作人员或管理员开放")
            try:
                self._appointment_states.require(AppointmentStatus(record.status), target)
            except DomainRuleViolation as exc:
                raise ConflictError(str(exc), "invalid_appointment_transition") from exc
            record.status = target.value
            await self._audit(
                session, actor_id, "appointment.advanced", "appointment", record.id,
                {"status": target.value},
            )
            return self._appointment_dict(record)

    async def create_payment(self, account_id: UUID, application_id: UUID) -> dict[str, Any]:
        async with self._transaction() as session:
            app = await session.get(
                ApplicationRecord, application_id, with_for_update=True
            )
            if app is None or app.applicant_id != account_id:
                raise ResourceNotFound("办件")
            if app.status != ApplicationStatus.AWAITING_PAYMENT.value:
                raise ConflictError("办件当前无需缴费")
            version = await session.get(ServiceVersionRecord, app.service_version_id)
            existing = await session.scalar(select(PaymentOrderRecord).where(PaymentOrderRecord.application_id == application_id, PaymentOrderRecord.status.in_(["CREATED", "PENDING", "SUCCEEDED"])))
            if existing:
                return self._payment_dict(existing)
            amount_cents = version.fee_cents if version else 0
            if version and version.fee_calculation:
                fund = app.form_data.get("fund", {}) if isinstance(app.form_data, dict) else {}
                try:
                    amount_cents = round(float(fund.get("contribution_base", 0)) * float(fund.get("contribution_ratio", 0)) * 100)
                except (TypeError, ValueError):
                    amount_cents = 0
                if amount_cents <= 0:
                    raise ConflictError("无法根据缴存基数和比例生成模拟缴付金额")
            record = PaymentOrderRecord(application_id=application_id, account_id=account_id, amount_cents=amount_cents, status="CREATED")
            session.add(record); await session.flush()
            return self._payment_dict(record)

    async def cancel_payment(
        self, payment_id: UUID, account_id: UUID
    ) -> dict[str, Any]:
        async with self._transaction() as session:
            record = await session.get(
                PaymentOrderRecord, payment_id, with_for_update=True
            )
            if record is None or record.account_id != account_id:
                raise ResourceNotFound("缴费订单")
            try:
                self._payment_states.require(
                    PaymentStatus(record.status), PaymentStatus.CANCELLED
                )
            except DomainRuleViolation as exc:
                raise ConflictError(
                    str(exc), "invalid_payment_transition"
                ) from exc
            record.status = PaymentStatus.CANCELLED.value
            await self._audit(
                session, account_id, "payment.cancelled", "payment", record.id, {}
            )
            return self._payment_dict(record)

    async def get_payment(self, payment_id: UUID, account_id: UUID) -> PaymentOrderRecord:
        async with self.sessions() as session:
            record = await session.get(PaymentOrderRecord, payment_id)
            if record is None or record.account_id != account_id:
                raise ResourceNotFound("缴费订单")
            return record

    async def application_requires_payment(self, application_id: UUID) -> bool:
        async with self.sessions() as session:
            app = await session.get(ApplicationRecord, application_id)
            if app is None:
                raise ResourceNotFound("办件")
            version = await session.get(ServiceVersionRecord, app.service_version_id)
            return bool(version and version.fee_required)

    async def update_payment(self, payment_id: UUID, account_id: UUID, outcome: str, provider_reference: str) -> dict[str, Any]:
        async with self._transaction() as session:
            snapshot = await session.get(PaymentOrderRecord, payment_id)
            if snapshot is None or snapshot.account_id != account_id:
                raise ResourceNotFound("缴费订单")
            app = await session.get(
                ApplicationRecord, snapshot.application_id, with_for_update=True
            )
            record = await session.get(
                PaymentOrderRecord, payment_id,
                with_for_update=True, populate_existing=True,
            )
            if record is None or app is None:
                raise ResourceNotFound("缴费订单")
            if app.status != ApplicationStatus.AWAITING_PAYMENT.value:
                raise ConflictError(
                    "关联办件已不在待缴费状态",
                    "payment_application_closed",
                )
            if record.status == "SUCCEEDED":
                return self._payment_dict(record)
            if record.status != "PENDING":
                raise ConflictError("缴费订单状态不可处理")
            record.status = "SUCCEEDED" if outcome == "success" else "FAILED"
            record.provider_reference = provider_reference
            if outcome == "success":
                app.status = ApplicationStatus.PROCESSING.value; app.version += 1
                service = await session.get(GovernmentServiceRecord, app.service_id)
                if service is not None:
                    session.add(ReviewTaskRecord(
                        application_id=app.id,
                        department_id=service.department_id,
                        status="PENDING",
                    ))
                await self._event(session, app, account_id, "application.payment_succeeded", ApplicationStatus.AWAITING_PAYMENT, ApplicationStatus.PROCESSING, {})
            await self._audit(session, account_id, "payment.processed", "payment", record.id, {"status": record.status})
            return self._payment_dict(record)

    async def mark_payment_pending(self, payment_id: UUID, account_id: UUID) -> dict[str, Any]:
        async with self._transaction() as session:
            snapshot = await session.get(PaymentOrderRecord, payment_id)
            if snapshot is None or snapshot.account_id != account_id:
                raise ResourceNotFound("缴费订单")
            app = await session.get(
                ApplicationRecord, snapshot.application_id, with_for_update=True
            )
            record = await session.get(
                PaymentOrderRecord, payment_id,
                with_for_update=True, populate_existing=True,
            )
            if record is None or app is None:
                raise ResourceNotFound("缴费订单")
            if app.status != ApplicationStatus.AWAITING_PAYMENT.value:
                raise ConflictError(
                    "关联办件已不在待缴费状态",
                    "payment_application_closed",
                )
            if record.status == "SUCCEEDED":
                return self._payment_dict(record)
            if record.status not in {"CREATED", "FAILED", "PENDING"}:
                raise ConflictError("缴费订单状态不可处理")
            record.status = "PENDING"
            await self._audit(session, account_id, "payment.pending", "payment", record.id, {})
            return self._payment_dict(record)

    async def create_verification(self, account_id: UUID, application_id: UUID, expires_at: datetime) -> dict[str, Any]:
        async with self._transaction() as session:
            app = await session.get(
                ApplicationRecord, application_id, with_for_update=True
            )
            if app is None or app.applicant_id != account_id:
                raise ResourceNotFound("办件")
            if app.status not in {
                ApplicationStatus.DRAFT.value,
                ApplicationStatus.NEEDS_SUPPLEMENT.value,
            }:
                raise ConflictError(
                    "当前办件状态不能进行身份核验",
                    "verification_application_closed",
                )
            version = await session.get(ServiceVersionRecord, app.service_version_id)
            if version is None or not version.requires_verification:
                raise ConflictError("该事项不需要身份核验")
            record = VerificationSessionRecord(application_id=application_id, account_id=account_id, status="CREATED", expires_at=expires_at)
            session.add(record); await session.flush()
            return self._verification_dict(record)

    async def complete_verification(self, account_id: UUID, verification_id: UUID, outcome: str) -> dict[str, Any]:
        async with self._transaction() as session:
            snapshot = await session.get(VerificationSessionRecord, verification_id)
            if snapshot is None or snapshot.account_id != account_id:
                raise ResourceNotFound("身份核验")
            app = await session.get(
                ApplicationRecord, snapshot.application_id, with_for_update=True
            )
            record = await session.get(
                VerificationSessionRecord, verification_id,
                with_for_update=True, populate_existing=True,
            )
            if record is None or app is None:
                raise ResourceNotFound("身份核验")
            if app.status not in {
                ApplicationStatus.DRAFT.value,
                ApplicationStatus.NEEDS_SUPPLEMENT.value,
            }:
                raise ConflictError(
                    "关联办件已不允许继续身份核验",
                    "verification_application_closed",
                )
            if record.status != "CREATED":
                raise ConflictError("核验会话已结束")
            if record.expires_at <= datetime.now(timezone.utc):
                record.status = "EXPIRED"
            else:
                record.status = "PASSED" if outcome == "pass" else "FAILED"
            await self._audit(session, account_id, "verification.completed", "verification", record.id, {"status": record.status, "biometric_data_stored": False})
            return self._verification_dict(record)

    async def preflight_delivery(
        self, account_id: UUID, application_id: UUID
    ) -> dict[str, Any] | None:
        """Lock the aggregate before the external demo provider is called.

        The lock lives in the idempotent root UoW. Requests using different
        idempotency keys therefore serialize on the application and only the
        winner creates an external delivery reference.
        """
        async with self._transaction() as session:
            app = await session.get(
                ApplicationRecord, application_id, with_for_update=True
            )
            if app is None or app.applicant_id != account_id:
                raise ResourceNotFound("办件")
            if app.status not in {
                ApplicationStatus.PROCESSING.value,
                ApplicationStatus.COMPLETED.value,
            }:
                raise ConflictError("办件进入办理中或已完成状态后才能选择邮寄")
            version = await session.get(ServiceVersionRecord, app.service_version_id)
            service = await session.get(GovernmentServiceRecord, app.service_id)
            delivery = demo_delivery_contract(
                service.external_item_id if service else None,
                bool(version and version.delivery_supported),
            )
            if not delivery["mail_supported"]:
                raise ConflictError("该事项不支持邮寄")
            existing = await session.scalar(
                select(DeliveryOrderRecord).where(
                    DeliveryOrderRecord.application_id == application_id
                )
            )
            return self._delivery_dict(existing) if existing else None

    async def create_delivery(self, account_id: UUID, application_id: UUID, masked_recipient: str, masked_address: str, provider_reference: str) -> dict[str, Any]:
        async with self._transaction() as session:
            app = await session.get(
                ApplicationRecord, application_id, with_for_update=True
            )
            if app is None or app.applicant_id != account_id:
                raise ResourceNotFound("办件")
            if app.status not in {ApplicationStatus.PROCESSING.value, ApplicationStatus.COMPLETED.value}:
                raise ConflictError("办件进入办理中或已完成状态后才能选择邮寄")
            version = await session.get(ServiceVersionRecord, app.service_version_id)
            service = await session.get(GovernmentServiceRecord, app.service_id)
            delivery = demo_delivery_contract(
                service.external_item_id if service else None,
                bool(version and version.delivery_supported),
            )
            if not delivery["mail_supported"]:
                raise ConflictError("该事项不支持邮寄")
            existing = await session.scalar(select(DeliveryOrderRecord).where(DeliveryOrderRecord.application_id == application_id))
            if existing:
                return self._delivery_dict(existing)
            record = DeliveryOrderRecord(application_id=application_id, account_id=account_id, status="ACCEPTED", masked_recipient=masked_recipient, masked_address=masked_address, provider_reference=provider_reference)
            session.add(record); await session.flush()
            await self._audit(session, account_id, "delivery.created", "delivery", record.id, {"address": masked_address})
            return self._delivery_dict(record)

    async def advance_delivery(
        self,
        actor_id: UUID,
        role: Role,
        department_id: UUID | None,
        delivery_id: UUID,
        target: DeliveryStatus,
    ) -> dict[str, Any]:
        async with self._transaction() as session:
            record = await session.get(DeliveryOrderRecord, delivery_id, with_for_update=True)
            if record is None:
                raise ResourceNotFound("邮寄订单")
            app = await session.get(ApplicationRecord, record.application_id)
            service = await session.get(GovernmentServiceRecord, app.service_id) if app else None
            if role is Role.STAFF and (
                department_id is None or service is None or service.department_id != department_id
            ):
                raise PermissionDenied("只能处理本部门办件邮寄")
            if role not in {Role.STAFF, Role.ADMIN}:
                raise PermissionDenied("该功能仅向工作人员或管理员开放")
            try:
                self._delivery_states.require(DeliveryStatus(record.status), target)
            except DomainRuleViolation as exc:
                raise ConflictError(str(exc), "invalid_delivery_transition") from exc
            record.status = target.value
            await self._audit(
                session, actor_id, "delivery.advanced", "delivery", record.id,
                {"status": target.value},
            )
            return self._delivery_dict(record)

    async def cancel_delivery(
        self, account_id: UUID, delivery_id: UUID
    ) -> dict[str, Any]:
        async with self._transaction() as session:
            record = await session.get(
                DeliveryOrderRecord, delivery_id, with_for_update=True
            )
            if record is None or record.account_id != account_id:
                raise ResourceNotFound("邮寄订单")
            try:
                self._delivery_states.require(
                    DeliveryStatus(record.status), DeliveryStatus.CANCELLED
                )
            except DomainRuleViolation as exc:
                raise ConflictError(
                    str(exc), "invalid_delivery_transition"
                ) from exc
            record.status = DeliveryStatus.CANCELLED.value
            await self._audit(
                session, account_id, "delivery.cancelled", "delivery", record.id, {}
            )
            return self._delivery_dict(record)

    async def get_idempotent(self, actor_id: UUID, scope: str, key: str, request_hash: str) -> dict[str, Any] | None:
        async with self.sessions() as session:
            record = await session.scalar(select(IdempotencyRecord).where(IdempotencyRecord.actor_id == actor_id, IdempotencyRecord.scope == scope, IdempotencyRecord.idempotency_key == key))
            if record is None:
                return None
            if record.request_hash != request_hash:
                raise ConflictError("同一 Idempotency-Key 不能用于不同请求", "idempotency_key_reused")
            return record.response_json

    async def store_idempotent(self, actor_id: UUID, scope: str, key: str, request_hash: str, response: dict[str, Any]) -> dict[str, Any]:
        safe = json.loads(json.dumps(response, default=str, ensure_ascii=False))
        try:
            async with self._transaction() as session:
                session.add(IdempotencyRecord(actor_id=actor_id, scope=scope, idempotency_key=key, request_hash=request_hash, status_code=200, response_json=safe))
        except IntegrityError:
            existing = await self.get_idempotent(actor_id, scope, key, request_hash)
            if existing is not None:
                return existing
            raise
        return safe

    async def list_accounts(self) -> list[dict[str, Any]]:
        async with self.sessions() as session:
            return [account_view(item) for item in (await session.scalars(select(AccountRecord).order_by(AccountRecord.created_at.desc()))).all()]

    async def create_staff_account(
        self, actor_id: UUID, username: str, password_hash: str, display_name: str,
        department_id: UUID, window_id: UUID | None,
    ) -> dict[str, Any]:
        try:
            async with self._transaction() as session:
                department = await session.get(DepartmentRecord, department_id)
                window = await session.get(ServiceWindowRecord, window_id) if window_id else None
                if department is None:
                    raise ResourceNotFound("部门")
                if window_id and (window is None or window.department_id != department_id):
                    raise ResourceNotFound("部门窗口")
                record = AccountRecord(
                    username=username.strip().lower(), password_hash=password_hash,
                    display_name=display_name.strip(), role=Role.STAFF.value,
                    applicant_type=None, active=True, token_version=0,
                    department_id=department_id, profile_json={"demo": True},
                )
                session.add(record); await session.flush()
                session.add(StaffAssignmentRecord(
                    account_id=record.id, department_id=department_id,
                    window_id=window_id, active=True,
                ))
                await self._audit(session, actor_id, "staff.created", "account", record.id, {"department_id": str(department_id)})
                return account_view(record)
        except IntegrityError as exc:
            raise ConflictError("用户名已存在", "username_exists") from exc

    async def list_windows(self, department_id: UUID | None = None) -> list[dict[str, Any]]:
        async with self.sessions() as session:
            statement = select(ServiceWindowRecord).order_by(ServiceWindowRecord.code)
            if department_id:
                statement = statement.where(ServiceWindowRecord.department_id == department_id)
            return [self._window_dict(item) for item in (await session.scalars(statement)).all()]

    async def import_navigation_catalog(
        self,
        actor_id: UUID,
        rows: tuple[NavigationCatalogRowData, ...],
        dry_run: bool,
    ) -> dict[str, Any]:
        """Atomically replace links for services represented by the CSV snapshot."""

        service_codes = {row.service_code for row in rows}
        window_codes = {row.window_code for row in rows}
        try:
            async with self.sessions() as session:
                async with session.begin():
                    services = {
                        item.code: item
                        for item in (
                            await session.scalars(
                                select(GovernmentServiceRecord).where(
                                    GovernmentServiceRecord.code.in_(service_codes)
                                ).with_for_update()
                            )
                        ).all()
                    }
                    existing_windows = {
                        item.code: item
                        for item in (
                            await session.scalars(
                                select(ServiceWindowRecord).where(
                                    ServiceWindowRecord.code.in_(window_codes)
                                ).with_for_update()
                            )
                        ).all()
                    }
                    errors: list[dict[str, Any]] = []
                    window_departments: dict[str, UUID] = {}
                    for row in rows:
                        service = services.get(row.service_code)
                        if service is None:
                            errors.append(
                                {
                                    "line": row.line_number,
                                    "field": "service_code",
                                    "message": "事项编码不存在",
                                }
                            )
                            continue
                        expected_department = window_departments.setdefault(
                            row.window_code, service.department_id
                        )
                        if expected_department != service.department_id:
                            errors.append(
                                {
                                    "line": row.line_number,
                                    "field": "window_code",
                                    "message": "同一网点不能跨部门关联",
                                }
                            )
                        existing = existing_windows.get(row.window_code)
                        if (
                            existing is not None
                            and existing.department_id != service.department_id
                        ):
                            errors.append(
                                {
                                    "line": row.line_number,
                                    "field": "window_code",
                                    "message": "网点已属于其他部门",
                                }
                            )
                    report = {
                        "valid": not errors,
                        "dry_run": dry_run,
                        "rows": len(rows),
                        "services": len(service_codes),
                        "windows": len(window_codes),
                        "links": len(rows),
                        "written": False,
                        "errors": errors[:100],
                    }
                    if errors or dry_run:
                        return report

                    # A CSV import is a full snapshot for every service named
                    # in the file.  Load the pre-existing associations inside
                    # this same transaction so rows omitted from the snapshot
                    # can be disabled atomically without disabling a window
                    # that another service may still use.
                    existing_link_rows = list(
                        (
                            await session.scalars(
                                select(ServiceWindowLinkRecord).where(
                                    ServiceWindowLinkRecord.service_id.in_(
                                        {service.id for service in services.values()}
                                    )
                                )
                            )
                        ).all()
                    )

                    imported_at = datetime.now(timezone.utc)
                    service_rows: dict[str, NavigationCatalogRowData] = {}
                    window_rows: dict[str, NavigationCatalogRowData] = {}
                    for row in rows:
                        service_rows.setdefault(row.service_code, row)
                        window_rows.setdefault(row.window_code, row)

                    for code, row in service_rows.items():
                        service = services[code]
                        service.handling_mode = row.handling_mode
                        service.online_status = row.online_status
                        service.status_reason = (
                            "导航目录导入：仅线下办理"
                            if row.handling_mode == "OFFLINE_ONLY"
                            else (
                                "导航目录导入：线上渠道暂不可用"
                                if row.online_status == "TEMP_UNAVAILABLE"
                                else "导航目录导入"
                            )
                        )
                        service.status_updated_at = row.verified_at or imported_at

                    for code, row in window_rows.items():
                        window = existing_windows.get(code)
                        if window is None:
                            window = ServiceWindowRecord(
                                department_id=window_departments[code],
                                code=code,
                                capacity_per_slot=10,
                                active=True,
                            )
                            session.add(window)
                            existing_windows[code] = window
                        window.name = row.name
                        window.address = row.address
                        window.city_code = row.city_code
                        window.longitude = row.longitude
                        window.latitude = row.latitude
                        window.coordinate_type = row.coordinate_type
                        window.opening_hours = row.opening_hours
                        window.data_mode = row.data_mode
                        window.source_reference = row.source_reference
                        window.verified_at = row.verified_at
                        window.active = True
                    await session.flush()

                    snapshot_link_keys: set[tuple[UUID, UUID]] = set()
                    for row in rows:
                        service = services[row.service_code]
                        window = existing_windows[row.window_code]
                        snapshot_link_keys.add((service.id, window.id))
                        link = await session.get(
                            ServiceWindowLinkRecord, (service.id, window.id)
                        )
                        if link is None:
                            link = ServiceWindowLinkRecord(
                                service_id=service.id,
                                window_id=window.id,
                            )
                            session.add(link)
                        link.priority = row.priority
                        link.active = True

                    deactivated_links = 0
                    for link in existing_link_rows:
                        if (link.service_id, link.window_id) not in snapshot_link_keys:
                            if link.active:
                                deactivated_links += 1
                            link.active = False

                    # Keep the legacy single-window field useful during the
                    # compatibility release.  It follows the active snapshot's
                    # highest-priority row (stable code tie-break), never an
                    # association that was just disabled.
                    snapshot_rows_by_service: dict[
                        str, list[NavigationCatalogRowData]
                    ] = {}
                    for row in rows:
                        snapshot_rows_by_service.setdefault(
                            row.service_code, []
                        ).append(row)
                    for code, service in services.items():
                        candidates = snapshot_rows_by_service.get(code, [])
                        if not candidates:
                            service.window_id = None
                            continue
                        primary = min(
                            candidates,
                            key=lambda item: (
                                item.priority,
                                item.window_code,
                                item.line_number,
                            ),
                        )
                        service.window_id = existing_windows[primary.window_code].id

                    await self._audit(
                        session,
                        actor_id,
                        "navigation_catalog.imported",
                        "navigation_catalog",
                        "csv",
                        {
                            "rows": len(rows),
                            "services": len(service_codes),
                            "windows": len(window_codes),
                            "links": len(rows),
                            "deactivated_links": deactivated_links,
                        },
                    )
                    report["written"] = True
                    return report
        except IntegrityError as exc:
            raise ConflictError(
                "导航目录在导入期间发生并发冲突，请重新执行dry-run",
                "navigation_catalog_conflict",
            ) from exc

    async def create_digital_human_intent(
        self,
        owner_account_id: UUID | None,
        owner_role: Role | None,
        client_session_id: UUID,
        provider_session_id_hash: str,
        intent_type: str,
        label: str,
        section: str,
        prefill: dict[str, Any],
        expires_at: datetime,
    ) -> dict[str, Any]:
        record = DigitalHumanActionIntentRecord(
            owner_account_id=owner_account_id,
            owner_role=owner_role.value if owner_role else None,
            client_session_id=client_session_id,
            chat_id_hash=provider_session_id_hash,
            intent_type=intent_type,
            label=label,
            section=section,
            prefill_json=redact_sensitive(prefill),
            status=DigitalHumanIntentStatus.ACTIVE.value,
            expires_at=expires_at,
        )
        async with self._transaction() as session:
            session.add(record)
            await session.flush()
            await self._audit(
                session,
                owner_account_id,
                "digital_human.intent_created",
                "digital_human_action_intent",
                record.id,
                {
                    "type": intent_type,
                    "section": section,
                    "expires_at": expires_at.isoformat(),
                },
            )
        return {
            "id": record.id,
            "type": record.intent_type,
            "label": record.label,
            "section": record.section,
            "prefill": dict(record.prefill_json),
            "expires_at": record.expires_at,
        }

    async def consume_digital_human_intent(
        self,
        intent_id: UUID,
        actor_id: UUID | None,
        actor_role: Role | None,
        client_session_id: UUID,
        client_chat_id_hash: str,
        now: datetime,
        required_intent_type: str | None = None,
    ) -> dict[str, Any]:
        async with self._transaction() as session:
            record = await session.scalar(
                select(DigitalHumanActionIntentRecord)
                .where(DigitalHumanActionIntentRecord.id == intent_id)
                .with_for_update()
            )
            if (
                record is None
                or record.owner_account_id != actor_id
                or record.owner_role != (
                    actor_role.value if actor_role is not None else None
                )
                or record.client_session_id != client_session_id
            ):
                # Deliberately conceal whether another account owns the intent.
                raise ResourceNotFound("数字人操作意图")
            if (
                required_intent_type is not None
                and record.intent_type != required_intent_type
            ):
                # This check is deliberately inside the row lock and before
                # consumption: an anonymous caller must not burn a protected
                # workbench intent merely to discover that login is required.
                raise AuthenticationRequired("请先登录后继续")
            if record.intent_type == "OPEN_SERVICE_NAVIGATION":
                prefill = record.prefill_json
                try:
                    service_id_value = prefill["service_id"]
                    UUID(str(service_id_value))
                except (KeyError, TypeError, ValueError, AttributeError) as exc:
                    raise ResourceNotFound("数字人操作意图") from exc
                if (
                    record.section != "services"
                    or not isinstance(prefill, dict)
                    or set(prefill) != {"service_id"}
                ):
                    raise ResourceNotFound("数字人操作意图")
            if record.status != DigitalHumanIntentStatus.ACTIVE.value:
                raise ConflictError(
                    "数字人操作意图已使用",
                    "digital_human_intent_consumed",
                )
            expires_at = record.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= now:
                raise ConflictError(
                    "数字人操作意图已过期",
                    "digital_human_intent_expired",
                )
            record.status = DigitalHumanIntentStatus.CONSUMED.value
            record.consumed_at = now
            await self._audit(
                session,
                actor_id,
                "digital_human.intent_exchanged",
                "digital_human_action_intent",
                record.id,
                {
                    "type": record.intent_type,
                    "section": record.section,
                    # Android's semanticRecognized.chatId is per-turn and is
                    # not the provider callback session_id stored on creation.
                    # Keep only a pseudonymous audit correlation; ownership,
                    # role, opaque client session, expiry and row lock are the
                    # actual authorization boundaries.
                    "client_chat_id_hash": client_chat_id_hash,
                },
            )
            return {
                "intent_id": record.id,
                "type": record.intent_type,
                "label": record.label,
                "section": record.section,
                "prefill": dict(record.prefill_json),
            }

    async def list_audits(self, limit: int = 100) -> list[dict[str, Any]]:
        async with self.sessions() as session:
            items = (await session.scalars(select(BusinessAuditEventRecord).order_by(BusinessAuditEventRecord.created_at.desc()).limit(limit))).all()
            return [{"id": item.id, "actor_id": item.actor_id, "action": item.action, "resource_type": item.resource_type, "resource_id": item.resource_id, "detail": redact_sensitive(item.detail_json), "created_at": item.created_at} for item in items]

    async def metrics(self) -> dict[str, int]:
        async with self.sessions() as session:
            tables = {"accounts": AccountRecord, "services": GovernmentServiceRecord, "applications": ApplicationRecord, "pending_tasks": ReviewTaskRecord, "handoffs": HandoffTicketRecord}
            result: dict[str, int] = {}
            for name, model in tables.items():
                statement = select(func.count()).select_from(model)
                if name == "pending_tasks": statement = statement.where(ReviewTaskRecord.status.in_(["PENDING", "CLAIMED"]))
                result[name] = int(await session.scalar(statement) or 0)
            return result

    async def create_knowledge_records(self, actor_id: UUID, document_id: str, title: str, source: str, content: str, object_key: str, chunks: list[str]) -> tuple[UUID, list[dict[str, Any]], bool, str]:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        async with self._transaction() as session:
            await session.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended(:name, 0))"
                ),
                {"name": f"smart-gov:knowledge-document:{document_id}"},
            )
            document = await session.get(KnowledgeDocument, document_id)
            object_retained = False
            if document is None:
                document = KnowledgeDocument(id=document_id, title=title, content=content, source=source, content_hash=digest, metadata_json={"demo": True, "object_key": object_key})
                session.add(document)
                object_retained = True
                # The index-job mapper lives in the infrastructure module while
                # KnowledgeDocument is retained from the original model module.
                # Flush the FK parent explicitly before inserting the job so
                # async PostgreSQL never observes the child first.
                await session.flush()
            elif not (document.metadata_json or {}).get("object_key"):
                document.metadata_json = {
                    **(document.metadata_json or {}),
                    "demo": True,
                    "object_key": object_key,
                }
                object_retained = True
            live_job = await session.scalar(
                select(KnowledgeIndexJobRecord)
                .where(
                    KnowledgeIndexJobRecord.document_id == document_id,
                    KnowledgeIndexJobRecord.status.in_(["ACTIVE", "INDEXING"]),
                )
                .order_by(KnowledgeIndexJobRecord.created_at.desc())
                .limit(1)
            )
            if live_job is None:
                job = KnowledgeIndexJobRecord(
                    document_id=document_id, status="INDEXING", attempts=1
                )
                session.add(job)
                await session.flush()
            else:
                job = live_job
            chunk_rows: list[dict[str, Any]] = []
            for index, chunk in enumerate(chunks):
                chunk_hash = hashlib.sha256(f"{document_id}:{index}:{chunk}".encode()).hexdigest()
                existing = await session.scalar(select(KnowledgeChunkRecord).where(KnowledgeChunkRecord.content_hash == chunk_hash))
                if existing is None:
                    existing = KnowledgeChunkRecord(document_id=document_id, chunk_index=index, content=chunk, content_hash=chunk_hash, metadata_json={"title": title, "source": source}, status="INDEXING")
                    session.add(existing); await session.flush()
                elif live_job is None:
                    existing.status = "INDEXING"
                chunk_rows.append({"id": str(existing.id), "title": title, "content": chunk, "source": source})
            await self._audit(
                session, actor_id,
                "knowledge.reused" if live_job is not None else "knowledge.uploaded",
                "knowledge_document", document_id,
                {"chunks": len(chunks), "job_id": str(job.id)},
            )
            return job.id, chunk_rows, object_retained, job.status

    async def finish_knowledge_job(self, job_id: UUID, success: bool, error: str | None = None) -> None:
        async with self._transaction() as session:
            job = await session.get(KnowledgeIndexJobRecord, job_id, with_for_update=True)
            if job is None: return
            job.status = "ACTIVE" if success else "INDEX_FAILED"
            job.last_error = error
            if success:
                await session.execute(
                    update(KnowledgeIndexJobRecord)
                    .where(
                        KnowledgeIndexJobRecord.document_id == job.document_id,
                        KnowledgeIndexJobRecord.id != job.id,
                        KnowledgeIndexJobRecord.status == "ACTIVE",
                    )
                    .values(status="SUPERSEDED")
                )
                chunk_status = "ACTIVE"
            else:
                other_active = await session.scalar(
                    select(KnowledgeIndexJobRecord.id).where(
                        KnowledgeIndexJobRecord.document_id == job.document_id,
                        KnowledgeIndexJobRecord.id != job.id,
                        KnowledgeIndexJobRecord.status == "ACTIVE",
                    )
                )
                chunk_status = "ACTIVE" if other_active else "INDEX_FAILED"
            await session.execute(
                update(KnowledgeChunkRecord)
                .where(KnowledgeChunkRecord.document_id == job.document_id)
                .values(status=chunk_status)
            )

    async def list_active_knowledge_chunks(self) -> list[dict[str, str]]:
        """Reconcile pre-status-field vectors after an in-place upgrade."""
        async with self.sessions() as session:
            chunks = list(
                (
                    await session.scalars(
                        select(KnowledgeChunkRecord)
                        .where(KnowledgeChunkRecord.status == "ACTIVE")
                        .order_by(
                            KnowledgeChunkRecord.document_id,
                            KnowledgeChunkRecord.chunk_index,
                        )
                    )
                ).all()
            )
            result: list[dict[str, str]] = []
            for item in chunks:
                document = await session.get(KnowledgeDocument, item.document_id)
                metadata = item.metadata_json or {}
                result.append(
                    {
                        "id": str(item.id),
                        "title": str(
                            metadata.get(
                                "title", document.title if document else "演示知识"
                            )
                        ),
                        "content": item.content,
                        "source": str(
                            metadata.get(
                                "source",
                                document.source if document else "demo://knowledge",
                            )
                        ),
                    }
                )
            return result

    async def recover_stale_knowledge_jobs(
        self, age_seconds: int | None = None
    ) -> int:
        """Turn startup-orphaned INDEXING jobs into retryable failures.

        The local deployment has one API process, so no indexing operation can
        survive that process restarting. Startup therefore recovers even fresh
        INDEXING rows. ``age_seconds`` remains available for a future rolling
        multi-replica deployment that supplies an explicit lease threshold.
        """
        async with self.sessions.begin() as session:
            statement = select(KnowledgeIndexJobRecord).where(
                KnowledgeIndexJobRecord.status == "INDEXING"
            )
            if age_seconds is not None:
                cutoff = datetime.now(timezone.utc) - timedelta(
                    seconds=age_seconds
                )
                statement = statement.where(
                    KnowledgeIndexJobRecord.updated_at < cutoff
                )
            jobs = list(
                (
                    await session.scalars(
                        statement.with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for job in jobs:
                job.status = "INDEX_FAILED"
                job.last_error = "stale_indexing_recovered"
                other_active = await session.scalar(
                    select(KnowledgeIndexJobRecord.id).where(
                        KnowledgeIndexJobRecord.document_id == job.document_id,
                        KnowledgeIndexJobRecord.id != job.id,
                        KnowledgeIndexJobRecord.status == "ACTIVE",
                    )
                )
                if other_active is None:
                    await session.execute(
                        update(KnowledgeChunkRecord)
                        .where(
                            KnowledgeChunkRecord.document_id == job.document_id
                        )
                        .values(status="INDEX_FAILED")
                    )
            return len(jobs)

    async def prepare_knowledge_retry(
        self, actor_id: UUID, job_id: UUID
    ) -> list[dict[str, Any]]:
        async with self._transaction() as session:
            job = await session.get(KnowledgeIndexJobRecord, job_id, with_for_update=True)
            if job is None:
                raise ResourceNotFound("知识索引任务")
            if job.status != "INDEX_FAILED":
                raise ConflictError("只有失败的知识索引任务可以重试")
            document = await session.get(KnowledgeDocument, job.document_id)
            if document is None:
                raise ResourceNotFound("知识文档")
            chunks = list((await session.scalars(
                select(KnowledgeChunkRecord)
                .where(KnowledgeChunkRecord.document_id == job.document_id)
                .order_by(KnowledgeChunkRecord.chunk_index)
            )).all())
            job.status = "INDEXING"
            job.attempts += 1
            job.last_error = None
            for chunk in chunks:
                chunk.status = "INDEXING"
            await self._audit(
                session, actor_id, "knowledge.retry", "knowledge_index_job", job.id,
                {"attempts": job.attempts},
            )
            return [
                {
                    "id": str(item.id),
                    "title": str(item.metadata_json.get("title", document.title)),
                    "content": item.content,
                    "source": str(item.metadata_json.get("source", document.source)),
                }
                for item in chunks
            ]

    async def archive_knowledge(
        self, actor_id: UUID, job_id: UUID
    ) -> dict[str, Any]:
        async with self._transaction() as session:
            job = await session.get(
                KnowledgeIndexJobRecord, job_id, with_for_update=True
            )
            if job is None:
                raise ResourceNotFound("知识索引任务")
            try:
                self._knowledge_states.require(
                    KnowledgeStatus(job.status), KnowledgeStatus.ARCHIVED
                )
            except DomainRuleViolation as exc:
                raise ConflictError(
                    str(exc), "invalid_knowledge_transition"
                ) from exc
            job.status = KnowledgeStatus.ARCHIVED.value
            other_active = await session.scalar(
                select(KnowledgeIndexJobRecord.id).where(
                    KnowledgeIndexJobRecord.document_id == job.document_id,
                    KnowledgeIndexJobRecord.id != job.id,
                    KnowledgeIndexJobRecord.status == KnowledgeStatus.ACTIVE.value,
                )
            )
            chunks = list(
                (
                    await session.scalars(
                        select(KnowledgeChunkRecord).where(
                            KnowledgeChunkRecord.document_id == job.document_id
                        )
                    )
                ).all()
            )
            chunk_ids: list[str] = []
            if other_active is None:
                await session.execute(
                    update(KnowledgeChunkRecord)
                    .where(KnowledgeChunkRecord.document_id == job.document_id)
                    .values(status=KnowledgeStatus.ARCHIVED.value)
                )
                chunk_ids = [str(item.id) for item in chunks]
            await self._audit(
                session, actor_id, "knowledge.archived",
                "knowledge_index_job", job.id, {},
            )
            return {
                "job_id": job.id,
                "document_id": job.document_id,
                "status": job.status,
                "demo_data": True,
                "_chunk_ids": chunk_ids,
            }

    async def seed_material_templates(self, templates: tuple[Any, ...]) -> None:
        async with self._transaction() as session:
            await session.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended(:name, 0))"
                ),
                {"name": "smart-gov:material-template-seed:v1"},
            )
            resolved: list[tuple[Any, MaterialTemplateRecord | None, dict[str, Any]]] = []
            for item in templates:
                service = await session.scalar(
                    select(GovernmentServiceRecord).where(
                        GovernmentServiceRecord.code == item.service_code
                    )
                )
                if service is None or service.current_version_id is None:
                    raise RuntimeError(
                        "material_template_service_missing:"
                        f"{item.service_code}:{item.template_key}"
                    )
                requirement = await session.scalar(
                    select(MaterialRequirementRecord).where(
                        MaterialRequirementRecord.service_version_id
                        == service.current_version_id,
                        MaterialRequirementRecord.code == item.requirement_code,
                    )
                )
                if requirement is None:
                    raise RuntimeError(
                        "material_template_requirement_missing:"
                        f"{item.service_code}:{item.requirement_code}:"
                        f"{item.template_key}"
                    )
                record = await session.scalar(
                    select(MaterialTemplateRecord).where(
                        MaterialTemplateRecord.template_key == item.template_key,
                        MaterialTemplateRecord.material_requirement_id
                        == requirement.id,
                    )
                )
                values = {
                    "material_requirement_id": requirement.id,
                    "service_code": item.service_code,
                    "requirement_code": item.requirement_code,
                    "title": item.title,
                    "mode": item.mode.value,
                    "source_object_key": item.source_object_key,
                    "source_sha256": item.source_sha256,
                    "allowed_fields": list(item.allowed_fields),
                    "notice": item.notice,
                    "active": True,
                }
                immutable_keys = {
                    "material_requirement_id",
                    "service_code",
                    "requirement_code",
                    "title",
                    "mode",
                    "source_object_key",
                    "source_sha256",
                    "allowed_fields",
                    "notice",
                }
                if record is not None and any(
                    getattr(record, key) != value
                    for key, value in values.items()
                    if key in immutable_keys
                ):
                    raise RuntimeError(
                        "material_template_immutable_conflict:"
                        f"{item.service_code}:{item.requirement_code}:"
                        f"{item.template_key}"
                    )
                resolved.append((item, record, values))

            # This catalog has no administrative writer: every row is owned by
            # this reviewed manifest. A key removed from the pack is therefore
            # disabled across versions. Rows for keys that remain present are
            # deliberately not bulk-reactivated: an old source recalled in a
            # prior manifest must stay disabled if the key is later reused by a
            # new service version. Only the resolved current row below may be
            # activated.
            manifest_keys = sorted({item.template_key for item in templates})
            if manifest_keys:
                await session.execute(
                    update(MaterialTemplateRecord)
                    .where(MaterialTemplateRecord.template_key.not_in(manifest_keys))
                    .values(active=False)
                )
            else:
                await session.execute(
                    update(MaterialTemplateRecord).values(active=False)
                )

            for item, record, values in resolved:
                if record is None:
                    session.add(
                        MaterialTemplateRecord(
                            template_key=item.template_key, version=1, **values
                        )
                    )
                else:
                    # All catalog semantics are immutable for this requirement
                    # and key; only reactivation after a manifest reintroduction
                    # is permitted.
                    record.active = True

    async def list_material_template_options(
        self, application_id: UUID, owner_account_id: UUID
    ) -> list[dict[str, Any]]:
        async with self.sessions() as session:
            application = await session.get(ApplicationRecord, application_id)
            if (
                application is None
                or application.applicant_id != owner_account_id
            ):
                raise ResourceNotFound("办件")
            service = await session.get(
                GovernmentServiceRecord, application.service_id
            )
            if (
                service is None
                or service.status != ServiceStatus.PUBLISHED.value
            ):
                raise ResourceNotFound("事项")
            rows = (
                await session.execute(
                    select(MaterialRequirementRecord, MaterialTemplateRecord)
                    .outerjoin(
                        MaterialTemplateRecord,
                        and_(
                            MaterialTemplateRecord.material_requirement_id
                            == MaterialRequirementRecord.id,
                            MaterialTemplateRecord.active.is_(True),
                        ),
                    )
                    .where(
                        MaterialRequirementRecord.service_version_id
                        == application.service_version_id
                    )
                    .order_by(
                        MaterialRequirementRecord.order_index,
                        MaterialTemplateRecord.template_key,
                    )
                )
            ).all()
            items: list[dict[str, Any]] = []
            for requirement, template in rows:
                mode = template.mode if template else MaterialTemplateMode.NOT_GENERATABLE.value
                available = bool(
                    template
                    and template.active
                    and mode != MaterialTemplateMode.NOT_GENERATABLE.value
                    and template.source_object_key
                    and template.source_sha256
                )
                items.append(
                    {
                        "requirement_code": requirement.code,
                        "requirement_name": requirement.name,
                        "template_available": available,
                        "template_id": template.id if available else None,
                        "template_title": template.title if template else None,
                        "mode": mode,
                        "notice": template.notice if template else "该材料不能由系统生成。",
                        "demo_data": True,
                    }
                )
            return items

    async def list_consultation_material_template_options(
        self, service_id: UUID | None = None, query: str | None = None
    ) -> list[dict[str, Any]]:
        if service_id is None:
            return await self.search_consultation_material_template_options(query or "")
        async with self.sessions() as session:
            service = await session.get(GovernmentServiceRecord, service_id)
            if (
                service is None
                or service.status != ServiceStatus.PUBLISHED.value
                or service.current_version_id is None
            ):
                raise ResourceNotFound("事项")
            service_version = await session.get(
                ServiceVersionRecord, service.current_version_id
            )
            if (
                service_version is None
                or service_version.service_id != service.id
                or not service_version.immutable
            ):
                raise ResourceNotFound("事项版本")
            rows = (
                await session.execute(
                    select(MaterialRequirementRecord, MaterialTemplateRecord)
                    .outerjoin(
                        MaterialTemplateRecord,
                        and_(
                            MaterialTemplateRecord.material_requirement_id
                            == MaterialRequirementRecord.id,
                            MaterialTemplateRecord.active.is_(True),
                        ),
                    )
                    .where(
                        MaterialRequirementRecord.service_version_id
                        == service.current_version_id
                    )
                    .order_by(
                        MaterialRequirementRecord.order_index,
                        MaterialTemplateRecord.template_key,
                    )
                )
            ).all()
            items: list[dict[str, Any]] = []
            for requirement, template in rows:
                mode = (
                    template.mode
                    if template
                    else MaterialTemplateMode.NOT_GENERATABLE.value
                )
                available = bool(
                    template
                    and template.active
                    and mode != MaterialTemplateMode.NOT_GENERATABLE.value
                    and template.source_object_key
                    and template.source_sha256
                )
                items.append(
                    {
                        "service_id": service.id,
                        "service_version_id": service_version.id,
                        "service_code": service.code,
                        "service_title": service_version.title,
                        "requirement_code": requirement.code,
                        "requirement_name": requirement.name,
                        "template_available": available,
                        "template_id": template.id if available else None,
                        "template_key": template.template_key if template else None,
                        "template_title": template.title if template else None,
                        "mode": mode,
                        "notice": (
                            template.notice
                            if template
                            else "该材料不能由系统生成。"
                        ),
                        "demo_data": True,
                    }
                )
            normalized_query = (query or "").strip().casefold()[:100]
            if normalized_query:
                items = [
                    item
                    for item in items
                    if normalized_query
                    in str(item["requirement_name"]).casefold()
                    or normalized_query
                    in str(item.get("template_title") or "").casefold()
                ]
            return items

    async def search_consultation_material_template_options(
        self, query: str
    ) -> list[dict[str, Any]]:
        normalized_query = query.strip()[:100]
        async with self.sessions() as session:
            statement = (
                select(
                    GovernmentServiceRecord,
                    ServiceVersionRecord,
                    MaterialRequirementRecord,
                    MaterialTemplateRecord,
                )
                .join(
                    ServiceVersionRecord,
                    and_(
                        ServiceVersionRecord.id
                        == GovernmentServiceRecord.current_version_id,
                        ServiceVersionRecord.service_id == GovernmentServiceRecord.id,
                    ),
                )
                .join(
                    MaterialRequirementRecord,
                    MaterialRequirementRecord.service_version_id
                    == ServiceVersionRecord.id,
                )
                .join(
                    MaterialTemplateRecord,
                    MaterialTemplateRecord.material_requirement_id
                    == MaterialRequirementRecord.id,
                )
                .where(
                    GovernmentServiceRecord.status == ServiceStatus.PUBLISHED.value,
                    ServiceVersionRecord.immutable.is_(True),
                    MaterialTemplateRecord.active.is_(True),
                    MaterialTemplateRecord.mode
                    != MaterialTemplateMode.NOT_GENERATABLE.value,
                    MaterialTemplateRecord.source_object_key.is_not(None),
                    MaterialTemplateRecord.source_sha256.is_not(None),
                )
            )
            if normalized_query:
                statement = statement.where(
                    or_(
                        MaterialRequirementRecord.name.contains(
                            normalized_query, autoescape=True
                        ),
                        MaterialTemplateRecord.title.contains(
                            normalized_query, autoescape=True
                        ),
                    )
                )
            rows = (
                await session.execute(
                    statement.order_by(
                        ServiceVersionRecord.title,
                        MaterialRequirementRecord.order_index,
                        MaterialTemplateRecord.template_key,
                    )
                )
            ).all()
            return [
                {
                    "service_id": service.id,
                    "service_version_id": service_version.id,
                    "service_code": service.code,
                    "service_title": service_version.title,
                    "requirement_code": requirement.code,
                    "requirement_name": requirement.name,
                    "template_available": True,
                    "template_id": template.id,
                    "template_key": template.template_key,
                    "template_title": template.title,
                    "mode": template.mode,
                    "notice": template.notice,
                    "demo_data": True,
                }
                for service, service_version, requirement, template in rows
            ]

    async def create_consultation_material_intent(
        self,
        owner_account_id: UUID,
        session_id: UUID,
        service_id: UUID,
        requirement_code: str,
        template_id: UUID,
        request_text: str | None,
        expires_at: datetime,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        request_text = request_text.strip() if request_text else None
        if request_text and len(request_text) > 300:
            raise BusinessValidationError("材料生成要求不能超过 300 个字符")
        if expires_at <= now:
            raise BusinessValidationError("材料生成确认有效期必须晚于当前时间")
        async with self._transaction() as session:
            chat = await session.get(ChatSession, session_id, with_for_update=True)
            if chat is None or chat.owner_account_id != owner_account_id:
                raise ResourceNotFound("咨询会话")
            service = await _require_material_document_service_published(
                session, service_id
            )
            if service.current_version_id is None:
                raise ConflictError(
                    "事项缺少已发布版本",
                    "material_document_service_version_unavailable",
                )
            service_version = await session.get(
                ServiceVersionRecord, service.current_version_id
            )
            if (
                service_version is None
                or service_version.service_id != service.id
                or not service_version.immutable
            ):
                raise ConflictError(
                    "事项版本当前不可用于生成材料",
                    "material_document_service_version_unavailable",
                )
            requirement = await session.scalar(
                select(MaterialRequirementRecord).where(
                    MaterialRequirementRecord.service_version_id
                    == service.current_version_id,
                    MaterialRequirementRecord.code == requirement_code,
                )
            )
            template = await session.get(MaterialTemplateRecord, template_id)
            if (
                requirement is None
                or template is None
                or template.material_requirement_id != requirement.id
                or not template.active
                or template.mode == MaterialTemplateMode.NOT_GENERATABLE.value
                or not template.source_object_key
                or not template.source_sha256
            ):
                raise ResourceNotFound("可生成材料模板")
            intent = ConsultationMaterialIntentRecord(
                owner_account_id=owner_account_id,
                session_id=session_id,
                service_id=service.id,
                service_version_id=service_version.id,
                material_requirement_id=requirement.id,
                template_id=template.id,
                requirement_code=requirement.code,
                status=ConsultationMaterialIntentStatus.PENDING.value,
                expires_at=expires_at,
            )
            session.add(intent)
            await session.flush()
            await self._audit(
                session,
                owner_account_id,
                "consultation_material.intent_created",
                "consultation_material_intent",
                intent.id,
                {
                    "session_id": str(session_id),
                    "service_id": str(service.id),
                    "requirement_code": requirement.code,
                    "template_id": str(template.id),
                },
            )
            return _consultation_material_intent_view(
                intent, requirement, template, service_version
            )

    async def get_consultation_material_intent_states(
        self,
        owner_account_id: UUID,
        session_id: UUID,
        intent_ids: tuple[UUID, ...],
        now: datetime,
    ) -> dict[UUID, dict[str, Any]]:
        if not intent_ids:
            return {}
        bounded_intent_ids = tuple(dict.fromkeys(intent_ids))[:100]
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(
                        ConsultationMaterialIntentRecord,
                        MaterialDocumentJobRecord,
                    )
                    .outerjoin(
                        MaterialDocumentJobRecord,
                        MaterialDocumentJobRecord.consultation_intent_id
                        == ConsultationMaterialIntentRecord.id,
                    )
                    .where(
                        ConsultationMaterialIntentRecord.owner_account_id
                        == owner_account_id,
                        ConsultationMaterialIntentRecord.session_id == session_id,
                        ConsultationMaterialIntentRecord.id.in_(bounded_intent_ids),
                    )
                )
            ).all()
            result: dict[UUID, dict[str, Any]] = {}
            for intent, job in rows:
                intent_expires_at = intent.expires_at
                if intent_expires_at.tzinfo is None:
                    intent_expires_at = intent_expires_at.replace(tzinfo=timezone.utc)
                intent_status = intent.status
                if (
                    intent_status == ConsultationMaterialIntentStatus.PENDING.value
                    and intent_expires_at <= now
                ):
                    intent_status = "EXPIRED"
                generation_status: str | None = None
                generation_expires_at: datetime | None = None
                if job is not None:
                    generation_status = job.status
                    generation_expires_at = job.expires_at
                    comparable_expiry = generation_expires_at
                    if comparable_expiry.tzinfo is None:
                        comparable_expiry = comparable_expiry.replace(
                            tzinfo=timezone.utc
                        )
                    if comparable_expiry <= now:
                        generation_status = MaterialDocumentStatus.EXPIRED.value
                result[intent.id] = {
                    "intent_id": intent.id,
                    "intent_status": intent_status,
                    "intent_expires_at": intent.expires_at,
                    "generation_id": job.id if job is not None else None,
                    "generation_status": generation_status,
                    "generation_expires_at": generation_expires_at,
                }
            return result

    async def get_latest_pending_consultation_material_intent(
        self, owner_account_id: UUID, session_id: UUID, now: datetime
    ) -> dict[str, Any] | None:
        async with self.sessions() as session:
            candidates = list(
                (
                    await session.scalars(
                        select(ConsultationMaterialIntentRecord)
                        .where(
                            ConsultationMaterialIntentRecord.owner_account_id
                            == owner_account_id,
                            ConsultationMaterialIntentRecord.session_id == session_id,
                            ConsultationMaterialIntentRecord.status
                            == ConsultationMaterialIntentStatus.PENDING.value,
                            ConsultationMaterialIntentRecord.expires_at > now,
                        )
                        .order_by(ConsultationMaterialIntentRecord.created_at.desc())
                        .limit(2)
                    )
                ).all()
            )
            # A follow-up such as “那就生成吧” is safe only when the server can
            # resolve exactly one still-valid candidate. Never default to the
            # most recent row when the conversation contains alternatives.
            if len(candidates) != 1:
                return None
            intent = candidates[0]
            service = await session.get(GovernmentServiceRecord, intent.service_id)
            requirement = await session.get(
                MaterialRequirementRecord, intent.material_requirement_id
            )
            template = await session.get(MaterialTemplateRecord, intent.template_id)
            service_version = await session.get(
                ServiceVersionRecord, intent.service_version_id
            )
            if (
                service is None
                or service.status != ServiceStatus.PUBLISHED.value
                or service.current_version_id != intent.service_version_id
                or requirement is None
                or requirement.service_version_id != intent.service_version_id
                or requirement.code != intent.requirement_code
                or template is None
                or template.material_requirement_id != requirement.id
                or not template.active
                or template.mode == MaterialTemplateMode.NOT_GENERATABLE.value
                or not template.source_object_key
                or not template.source_sha256
                or service_version is None
                or service_version.service_id != service.id
                or not service_version.immutable
            ):
                return None
            return _consultation_material_intent_view(
                intent, requirement, template, service_version
            )

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
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        async with self._transaction() as session:
            intent = await session.get(
                ConsultationMaterialIntentRecord, intent_id, with_for_update=True
            )
            if (
                intent is None
                or intent.owner_account_id != owner_account_id
                or intent.session_id != session_id
            ):
                # Conceal whether another account/session owns this intent.
                raise ResourceNotFound("材料生成确认")
            requirement = await session.get(
                MaterialRequirementRecord, intent.material_requirement_id
            )
            template = await session.get(MaterialTemplateRecord, intent.template_id)
            service_version = await session.get(
                ServiceVersionRecord, intent.service_version_id
            )
            if requirement is None or template is None or service_version is None:
                raise ResourceNotFound("材料生成确认")
            if intent.status == ConsultationMaterialIntentStatus.CONFIRMED.value:
                existing = await session.scalar(
                    select(MaterialDocumentJobRecord).where(
                        MaterialDocumentJobRecord.consultation_intent_id == intent.id
                    )
                )
                if existing is None:
                    raise ConflictError(
                        "材料生成确认状态异常",
                        "consultation_material_intent_integrity_failed",
                    )
                result = _material_document_view(existing)
                existing_expires_at = existing.expires_at
                if existing_expires_at.tzinfo is None:
                    existing_expires_at = existing_expires_at.replace(
                        tzinfo=timezone.utc
                    )
                if existing_expires_at <= now:
                    result["status"] = MaterialDocumentStatus.EXPIRED.value
                return result
            expires_at = intent.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= now:
                raise GoneError(
                    "材料生成确认已过期",
                    "consultation_material_intent_expired",
                )
            chat = await session.get(ChatSession, session_id, with_for_update=True)
            if chat is None or chat.owner_account_id != owner_account_id:
                raise ResourceNotFound("咨询会话")
            service = await _require_material_document_service_published(
                session, intent.service_id
            )
            if service.current_version_id != intent.service_version_id:
                raise ConflictError(
                    "事项版本已更新，请重新选择材料模板",
                    "consultation_material_intent_stale",
                )
            if (
                service_version.service_id != service.id
                or not service_version.immutable
                or requirement.service_version_id != service_version.id
                or requirement.code != intent.requirement_code
                or template.material_requirement_id != requirement.id
                or not template.active
                or template.mode == MaterialTemplateMode.NOT_GENERATABLE.value
                or not template.source_object_key
                or not template.source_sha256
            ):
                raise ConflictError(
                    "材料模板已更新，请重新选择",
                    "consultation_material_intent_stale",
                )
            await _enforce_material_document_job_limits(
                session,
                owner_account_id,
                now,
                user_daily_limit=user_daily_limit,
                user_active_limit=user_active_limit,
                global_daily_limit=global_daily_limit,
                global_queue_limit=global_queue_limit,
            )
            record = MaterialDocumentJobRecord(
                owner_account_id=owner_account_id,
                scope=MaterialDocumentScope.CONSULTATION.value,
                service_id=service.id,
                service_version_id=service_version.id,
                application_id=None,
                consultation_session_id=session_id,
                consultation_intent_id=intent.id,
                material_requirement_id=requirement.id,
                template_id=template.id,
                requirement_code=requirement.code,
                application_version=None,
                template_key_snapshot=template.template_key,
                template_version_snapshot=template.version,
                template_title_snapshot=template.title,
                template_mode_snapshot=template.mode,
                allowed_fields_snapshot=list(template.allowed_fields),
                source_object_key_snapshot=template.source_object_key,
                source_sha256_snapshot=template.source_sha256,
                model_name_snapshot=model_name[:128],
                release_lane=release_lane,
                status=MaterialDocumentStatus.QUEUED.value,
                form_snapshot={},
                # Consultation generation is deliberately a blank-template
                # operation. Chat prose/history must never reach the worker or
                # the external analyzer provider.
                request_text=None,
                expires_at=job_expires_at,
            )
            session.add(record)
            await session.flush()
            intent.status = ConsultationMaterialIntentStatus.CONFIRMED.value
            intent.confirmed_at = now
            await self._audit(
                session,
                owner_account_id,
                "consultation_material.intent_confirmed",
                "consultation_material_intent",
                intent.id,
                {
                    "generation_id": str(record.id),
                    "session_id": str(session_id),
                    "service_id": str(service.id),
                    "requirement_code": requirement.code,
                },
            )
            return _material_document_view(record)

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
    ) -> dict[str, Any]:
        async with self._transaction() as session:
            app = await session.get(ApplicationRecord, application_id, with_for_update=True)
            if app is None or app.applicant_id != owner_account_id:
                raise ResourceNotFound("办件")
            if app.status not in {
                ApplicationStatus.DRAFT.value,
                ApplicationStatus.NEEDS_SUPPLEMENT.value,
            }:
                raise ConflictError(
                    "当前办件状态不允许生成材料", "material_document_state_conflict"
                )
            await _require_material_document_service_published(session, app.service_id)
            requirement = await session.scalar(
                select(MaterialRequirementRecord).where(
                    MaterialRequirementRecord.service_version_id
                    == app.service_version_id,
                    MaterialRequirementRecord.code == requirement_code,
                )
            )
            template = await session.get(MaterialTemplateRecord, template_id)
            if (
                requirement is None
                or template is None
                or template.material_requirement_id != requirement.id
                or not template.active
                or template.mode == MaterialTemplateMode.NOT_GENERATABLE.value
                or not template.source_object_key
                or not template.source_sha256
            ):
                raise ResourceNotFound("可生成材料模板")
            await _enforce_material_document_job_limits(
                session,
                owner_account_id,
                datetime.now(timezone.utc),
                user_daily_limit=user_daily_limit,
                user_active_limit=user_active_limit,
                global_daily_limit=global_daily_limit,
                global_queue_limit=global_queue_limit,
            )
            snapshot = _project_form_snapshot(app.form_data, template.allowed_fields)
            record = MaterialDocumentJobRecord(
                owner_account_id=owner_account_id,
                scope=MaterialDocumentScope.APPLICATION.value,
                service_id=app.service_id,
                service_version_id=app.service_version_id,
                application_id=application_id,
                consultation_session_id=None,
                consultation_intent_id=None,
                material_requirement_id=requirement.id,
                template_id=template.id,
                requirement_code=requirement.code,
                application_version=app.version,
                template_key_snapshot=template.template_key,
                template_version_snapshot=template.version,
                template_title_snapshot=template.title,
                template_mode_snapshot=template.mode,
                allowed_fields_snapshot=list(template.allowed_fields),
                source_object_key_snapshot=template.source_object_key,
                source_sha256_snapshot=template.source_sha256,
                model_name_snapshot=model_name[:128],
                release_lane=release_lane,
                status=MaterialDocumentStatus.QUEUED.value,
                form_snapshot=snapshot,
                request_text=request_text,
                expires_at=expires_at,
            )
            session.add(record)
            await session.flush()
            await self._audit(
                session,
                owner_account_id,
                "material_document.queued",
                "material_document",
                record.id,
                {
                    "application_id": str(application_id),
                    "requirement_code": requirement.code,
                    "template_key": template.template_key,
                    "template_version": template.version,
                },
            )
            return _material_document_view(record)

    async def get_material_document_job_authorized(
        self, generation_id: UUID, owner_account_id: UUID
    ) -> dict[str, Any]:
        async with self.sessions() as session:
            record = await session.get(MaterialDocumentJobRecord, generation_id)
            if record is None or record.owner_account_id != owner_account_id:
                raise ResourceNotFound("生成文档")
            now = datetime.now(timezone.utc)
            result = _material_document_view(record, include_object=True)
            # Derive EXPIRED for the client, but leave the persisted terminal
            # status intact until the worker atomically claims the object key
            # for deletion. Mutating here would make cleanup skip the object.
            if record.expires_at <= now:
                result["status"] = MaterialDocumentStatus.EXPIRED.value
            return result

    async def lease_material_document_job(
        self, lease_seconds: int, release_lane: str
    ) -> LeasedMaterialDocumentJob | None:
        now = datetime.now(timezone.utc)
        async with self.sessions.begin() as session:
            stale = list(
                (
                    await session.scalars(
                        select(MaterialDocumentJobRecord)
                        .where(
                            MaterialDocumentJobRecord.release_lane == release_lane,
                            MaterialDocumentJobRecord.status
                            == MaterialDocumentStatus.RUNNING.value,
                            MaterialDocumentJobRecord.leased_until < now,
                        )
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for item in stale:
                item.status = MaterialDocumentStatus.FAILED.value
                item.error_code = "WORKER_INTERRUPTED"
                item.form_snapshot = None
                item.request_text = None
                item.lease_token = None
                item.leased_until = None
            job = await session.scalar(
                select(MaterialDocumentJobRecord)
                .where(
                    MaterialDocumentJobRecord.release_lane == release_lane,
                    MaterialDocumentJobRecord.status
                    == MaterialDocumentStatus.QUEUED.value,
                    MaterialDocumentJobRecord.expires_at > now,
                )
                .order_by(MaterialDocumentJobRecord.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if job is None:
                return None
            token = uuid4()
            job.status = MaterialDocumentStatus.RUNNING.value
            job.lease_token = token
            job.leased_until = now + timedelta(seconds=lease_seconds)
            snapshot = job.form_snapshot
            fields = job.allowed_fields_snapshot
            try:
                template_mode = MaterialTemplateMode(job.template_mode_snapshot)
            except ValueError:
                template_mode = None
            try:
                scope = MaterialDocumentScope(job.scope)
            except ValueError:
                scope = None
            context_valid = bool(
                scope is MaterialDocumentScope.APPLICATION
                and job.application_id is not None
                and job.consultation_session_id is None
                and job.consultation_intent_id is None
            ) or bool(
                scope is MaterialDocumentScope.CONSULTATION
                and job.application_id is None
                and job.consultation_session_id is not None
                and job.consultation_intent_id is not None
            )
            if (
                not isinstance(snapshot, dict)
                or not isinstance(fields, list)
                or any(not isinstance(item, str) for item in fields)
                or template_mode is None
                or scope is None
                or not context_valid
                or not job.service_id
                or not job.service_version_id
                or not job.template_key_snapshot
                or not job.template_title_snapshot
                or not job.source_object_key_snapshot
                or not job.source_sha256_snapshot
                or not job.model_name_snapshot
            ):
                job.status = MaterialDocumentStatus.FAILED.value
                job.error_code = "JOB_SNAPSHOT_INVALID"
                job.form_snapshot = None
                job.request_text = None
                job.lease_token = None
                job.leased_until = None
                return None
            return LeasedMaterialDocumentJob(
                id=job.id,
                owner_account_id=job.owner_account_id,
                application_id=job.application_id,
                requirement_code=job.requirement_code,
                template_id=job.template_id,
                template_key=job.template_key_snapshot,
                template_title=job.template_title_snapshot,
                template_mode=template_mode,
                allowed_fields=tuple(fields),
                source_object_key=job.source_object_key_snapshot,
                source_sha256=job.source_sha256_snapshot,
                form_snapshot=dict(snapshot),
                request_text=job.request_text,
                model_name=job.model_name_snapshot,
                lease_token=token,
                scope=scope,
                consultation_session_id=job.consultation_session_id,
            )

    async def renew_material_document_job_lease(
        self, generation_id: UUID, lease_token: UUID, lease_seconds: int
    ) -> bool:
        now = datetime.now(timezone.utc)
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(MaterialDocumentJobRecord)
                .where(
                    MaterialDocumentJobRecord.id == generation_id,
                    MaterialDocumentJobRecord.status
                    == MaterialDocumentStatus.RUNNING.value,
                    MaterialDocumentJobRecord.lease_token == lease_token,
                )
                .values(
                    leased_until=now + timedelta(seconds=lease_seconds),
                    updated_at=now,
                )
            )
            if result.rowcount == 1:
                return True
            # Completion clears the lease token atomically. A heartbeat that
            # was already in flight may observe READY immediately after the
            # worker committed its own output; that is success, not lease loss.
            status = await session.scalar(
                select(MaterialDocumentJobRecord.status).where(
                    MaterialDocumentJobRecord.id == generation_id
                )
            )
            return status == MaterialDocumentStatus.READY.value

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
    ) -> bool:
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(MaterialDocumentJobRecord)
                .where(
                    MaterialDocumentJobRecord.id == generation_id,
                    MaterialDocumentJobRecord.status
                    == MaterialDocumentStatus.RUNNING.value,
                    MaterialDocumentJobRecord.lease_token == lease_token,
                )
                .values(
                    status=MaterialDocumentStatus.READY.value,
                    output_object_key=object_key,
                    filename=filename[:255],
                    size_bytes=size_bytes,
                    sha256=sha256,
                    model_name=model_name[:128],
                    warnings=list(warnings),
                    error_code=None,
                    form_snapshot=None,
                    request_text=None,
                    lease_token=None,
                    leased_until=None,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            return result.rowcount == 1

    async def fail_material_document_job(
        self, generation_id: UUID, lease_token: UUID, error_code: str
    ) -> bool:
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(MaterialDocumentJobRecord)
                .where(
                    MaterialDocumentJobRecord.id == generation_id,
                    MaterialDocumentJobRecord.status
                    == MaterialDocumentStatus.RUNNING.value,
                    MaterialDocumentJobRecord.lease_token == lease_token,
                )
                .values(
                    status=MaterialDocumentStatus.FAILED.value,
                    error_code=error_code[:64],
                    form_snapshot=None,
                    request_text=None,
                    lease_token=None,
                    leased_until=None,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            return result.rowcount == 1

    async def expire_material_document_jobs(
        self, now: datetime
    ) -> list[str]:
        async with self.sessions.begin() as session:
            records = list(
                (
                    await session.scalars(
                        select(MaterialDocumentJobRecord)
                        .where(
                            MaterialDocumentJobRecord.expires_at <= now,
                            MaterialDocumentJobRecord.status.in_(
                                [
                                    MaterialDocumentStatus.READY.value,
                                    MaterialDocumentStatus.FAILED.value,
                                    MaterialDocumentStatus.QUEUED.value,
                                ]
                            ),
                        )
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            keys = [
                item.output_object_key
                for item in records
                if item.output_object_key
            ]
            for item in records:
                item.status = MaterialDocumentStatus.EXPIRED.value
                item.output_object_key = None
                item.form_snapshot = None
                item.request_text = None
                item.lease_token = None
                item.leased_until = None
            return keys

    async def _insert_version(self, session: AsyncSession, service_id: UUID, version_number: int, values: dict[str, Any]) -> ServiceVersionRecord:
        version = ServiceVersionRecord(
            service_id=service_id, version=version_number, title=values["title"], summary=values["summary"],
            form_schema=values.get("form_schema", {}), fee_cents=values.get("fee_cents", 0),
            fee_required=values.get("fee_required", values.get("fee_cents", 0) > 0),
            fee_calculation=values.get("fee_calculation"),
            appointment_supported=values.get("appointment_supported", values.get("requires_appointment", False)),
            requires_appointment=values.get("requires_appointment", False),
            requires_verification=values.get("requires_verification", False),
            delivery_supported=values.get("delivery_supported", False), immutable=False,
        )
        session.add(version); await session.flush()
        for index, item in enumerate(values.get("eligibility_rules", [])):
            session.add(EligibilityRuleRecord(service_version_id=version.id, rule_json=item.get("rule", item), failure_message=item.get("failure_message", "未满足办理条件"), order_index=index))
        for index, item in enumerate(values.get("materials", [])):
            session.add(MaterialRequirementRecord(service_version_id=version.id, code=item["code"], name=item["name"], required=item.get("required", True), condition_json=item.get("condition"), accepted_types=item.get("accepted_types", ["application/pdf", "image/jpeg", "image/png"]), order_index=index))
        for index, item in enumerate(values.get("process_steps", [])):
            session.add(ProcessStepRecord(service_version_id=version.id, order_index=item.get("order", index + 1), code=item.get("code", f"STEP_{index + 1}"), title=item["title"], actor=item.get("actor", "SYSTEM"), description=item.get("description", ""), expected_duration=item.get("expected_duration", "即时")))
        return version

    async def _require_application_access(self, session: AsyncSession, record: ApplicationRecord | None, actor_id: UUID, role: Role, department_id: UUID | None) -> None:
        if record is None: raise ResourceNotFound("办件")
        access_policy = getattr(
            self, "_case_access", AuthorizedCaseQueryService()
        )
        if access_policy.may_view(
            role, str(actor_id), str(record.applicant_id), same_department=False
        ):
            return
        if role is Role.STAFF:
            if record.status not in _REVIEW_TASK_APPLICATION_STATUSES:
                raise ResourceNotFound("办件")
            task = await session.scalar(
                select(ReviewTaskRecord.id).where(
                    ReviewTaskRecord.application_id == record.id,
                    ReviewTaskRecord.department_id == department_id,
                    ReviewTaskRecord.status.in_(["PENDING", "CLAIMED"]),
                    or_(
                        ReviewTaskRecord.assignee_id.is_(None),
                        ReviewTaskRecord.assignee_id == actor_id,
                    ),
                ).limit(1)
            )
            if task is not None:
                if access_policy.may_view(
                    role, str(actor_id), str(record.applicant_id),
                    same_department=True,
                ):
                    return
        raise ResourceNotFound("办件")

    async def _event(self, session: AsyncSession, app: ApplicationRecord, actor_id: UUID | None, event_type: str, from_status: ApplicationStatus | None, to_status: ApplicationStatus | None, detail: dict[str, Any]) -> None:
        session.add(ApplicationEventRecord(application_id=app.id, actor_id=actor_id, event_type=event_type, from_status=from_status.value if from_status else None, to_status=to_status.value if to_status else None, detail_json=redact_sensitive(detail)))

    async def _audit(self, session: AsyncSession, actor_id: UUID | None, action: str, resource_type: str, resource_id: object, detail: dict[str, Any]) -> None:
        session.add(BusinessAuditEventRecord(actor_id=actor_id, action=action, resource_type=resource_type, resource_id=str(resource_id), detail_json=redact_sensitive(detail)))

    @staticmethod
    def _service_summary(service: GovernmentServiceRecord, version: ServiceVersionRecord | None) -> dict[str, Any]:
        delivery = demo_delivery_contract(
            service.external_item_id,
            bool(version and version.delivery_supported),
        )
        return {"id": service.id, "external_item_id": service.external_item_id, "code": service.code, "title": version.title if version else "未命名事项", "summary": version.summary if version else "", "applicant_type": service.applicant_type, "status": service.status, "handling_mode": service.handling_mode, "online_status": service.online_status, "status_reason": service.status_reason, "status_updated_at": service.status_updated_at, "fee_required": version.fee_required if version else False, "fee_cents": version.fee_cents if version else 0, "fee_calculation": version.fee_calculation if version else None, "appointment_supported": version.appointment_supported if version else False, "requires_appointment": version.requires_appointment if version else False, "requires_verification": version.requires_verification if version else False, "delivery_supported": bool(delivery["supported"]), "delivery_options": delivery["options"], "mail_supported": delivery["mail_supported"], "demo_mail_supported": delivery["demo_mail_supported"], "demo_data": True}

    @staticmethod
    def _material_dict(item: MaterialRequirementRecord) -> dict[str, Any]:
        return {"id": item.id, "code": item.code, "name": item.name, "required": item.required, "condition": item.condition_json, "accepted_types": item.accepted_types}

    @staticmethod
    def _department_dict(item: DepartmentRecord) -> dict[str, Any]:
        return {"id": item.id, "code": item.code, "name": item.name, "active": item.active, "demo_data": True}

    @staticmethod
    def _window_dict(item: ServiceWindowRecord) -> dict[str, Any]:
        return {"id": item.id, "department_id": item.department_id, "code": item.code, "name": item.name, "address": item.address, "latitude": float(item.latitude), "longitude": float(item.longitude), "city_code": item.city_code, "opening_hours": item.opening_hours, "capacity_per_slot": item.capacity_per_slot, "active": item.active, "coordinate_type": item.coordinate_type, "data_mode": item.data_mode, "source_reference": item.source_reference, "verified_at": item.verified_at, "demo_data": item.data_mode == "DEMO"}

    @staticmethod
    def _navigation_window_dict(
        item: ServiceWindowRecord, priority: int
    ) -> dict[str, Any]:
        return {
            "id": item.id,
            "code": item.code,
            "name": item.name,
            "address": item.address,
            "opening_hours": item.opening_hours,
            "latitude": float(item.latitude),
            "longitude": float(item.longitude),
            "coordinate_type": item.coordinate_type,
            "priority": priority,
            "data_mode": item.data_mode,
            "city_code": item.city_code,
            "source_reference": item.source_reference,
            "verified_at": item.verified_at,
        }

    @staticmethod
    def _handoff_dict(item: HandoffTicketRecord) -> dict[str, Any]:
        return {"id": item.id, "session_id": item.session_id, "requester_id": item.requester_id, "department_id": item.department_id, "assignee_id": item.assignee_id, "status": item.status, "subject": item.subject, "created_at": item.created_at, "updated_at": item.updated_at, "demo_data": True}

    @staticmethod
    def _appointment_dict(item: AppointmentRecord) -> dict[str, Any]:
        return {"id": item.id, "service_id": item.service_id, "window_id": item.window_id, "slot_start": item.slot_start, "status": item.status, "demo_data": True}

    @staticmethod
    def _payment_dict(item: PaymentOrderRecord) -> dict[str, Any]:
        return {"id": item.id, "application_id": item.application_id, "amount_cents": item.amount_cents, "status": item.status, "provider_reference": item.provider_reference, "notice": "本地模拟缴费，未发生真实资金交易。", "demo_data": True}

    @staticmethod
    def _verification_dict(item: VerificationSessionRecord) -> dict[str, Any]:
        return {"id": item.id, "application_id": item.application_id, "status": item.status, "expires_at": item.expires_at, "biometric_data_stored": False, "notice": item.demo_notice, "demo_data": True}

    @staticmethod
    def _delivery_dict(item: DeliveryOrderRecord) -> dict[str, Any]:
        return {"id": item.id, "application_id": item.application_id, "status": item.status, "recipient": item.masked_recipient, "address": item.masked_address, "provider_reference": item.provider_reference, "notice": "本地模拟邮寄，未创建真实快递订单。", "demo_data": True}
