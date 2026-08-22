from __future__ import annotations

import hashlib
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
from app.domain.enums import (
    ApplicantType,
    AppointmentStatus,
    ApplicationStatus,
    DeliveryStatus,
    HandoffStatus,
    KnowledgeStatus,
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
    PermissionDenied,
    ResourceNotFound,
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
    ConsultationFeedbackRecord,
    DeliveryOrderRecord,
    DepartmentRecord,
    EligibilityRuleRecord,
    FaqEntryRecord,
    GovernmentServiceRecord,
    HandoffMessageRecord,
    HandoffTicketRecord,
    IdempotencyRecord,
    KnowledgeChunkRecord,
    KnowledgeIndexJobRecord,
    MaterialRequirementRecord,
    PaymentOrderRecord,
    PolicySourceRecord,
    ProcessStepRecord,
    RefreshTokenRecord,
    ReviewTaskRecord,
    ServiceVersionRecord,
    ServiceWindowRecord,
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
                        longitude=item["longitude"], opening_hours="工作日 09:00-17:00",
                        capacity_per_slot=10, active=True,
                    )
                    session.add(record)
                    await session.flush()
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
                if service is not None:
                    continue
                service = GovernmentServiceRecord(
                    code=item["code"], external_item_id=item["external_item_id"],
                    department_id=departments[item["department"]].id,
                    window_id=windows[item["window"]].id,
                    applicant_type=item["applicant_type"], status=ServiceStatus.PUBLISHED.value,
                )
                session.add(service)
                await session.flush()
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
            windows = list((await session.scalars(select(ServiceWindowRecord).where(ServiceWindowRecord.id == service.window_id, ServiceWindowRecord.active.is_(True)))).all()) if service.window_id else []
            return {
                **self._service_summary(service, version),
                "version": version.version,
                "version_id": version.id,
                "form_schema": version.form_schema,
                "eligibility_rules": [{"rule": item.rule_json, "failure_message": item.failure_message} for item in rules],
                "materials": [self._material_dict(item) for item in materials],
                "process_steps": [{"order": item.order_index, "code": item.code, "title": item.title, "actor": item.actor, "description": item.description, "expected_duration": item.expected_duration} for item in steps],
                "policy_sources": [{"title": item.title, "reference": item.reference} for item in sources],
                "windows": [self._window_dict(item) for item in windows],
                "notice": "全部事项、条件、窗口和政策来源均为本地演示数据。",
            }

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
                )
                session.add(service); await session.flush()
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
            sessions = (await session.scalars(select(ChatSession).where(ChatSession.owner_account_id == account_id).order_by(ChatSession.updated_at.desc()))).all()
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
        return {"id": service.id, "external_item_id": service.external_item_id, "code": service.code, "title": version.title if version else "未命名事项", "summary": version.summary if version else "", "applicant_type": service.applicant_type, "status": service.status, "fee_required": version.fee_required if version else False, "fee_cents": version.fee_cents if version else 0, "fee_calculation": version.fee_calculation if version else None, "appointment_supported": version.appointment_supported if version else False, "requires_appointment": version.requires_appointment if version else False, "requires_verification": version.requires_verification if version else False, "delivery_supported": bool(delivery["supported"]), "delivery_options": delivery["options"], "mail_supported": delivery["mail_supported"], "demo_mail_supported": delivery["demo_mail_supported"], "demo_data": True}

    @staticmethod
    def _material_dict(item: MaterialRequirementRecord) -> dict[str, Any]:
        return {"id": item.id, "code": item.code, "name": item.name, "required": item.required, "condition": item.condition_json, "accepted_types": item.accepted_types}

    @staticmethod
    def _department_dict(item: DepartmentRecord) -> dict[str, Any]:
        return {"id": item.id, "code": item.code, "name": item.name, "active": item.active, "demo_data": True}

    @staticmethod
    def _window_dict(item: ServiceWindowRecord) -> dict[str, Any]:
        return {"id": item.id, "department_id": item.department_id, "code": item.code, "name": item.name, "address": item.address, "latitude": float(item.latitude), "longitude": float(item.longitude), "opening_hours": item.opening_hours, "capacity_per_slot": item.capacity_per_slot, "active": item.active, "coordinate_type": "DEMO_GCJ02", "demo_data": True}

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
