from __future__ import annotations

import ast
import asyncio
import inspect
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import jwt
import pytest
from pydantic import ValidationError

from app.domain.entities import MaterialRequirement
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
    AppointmentStateMachine,
    DeliveryStateMachine,
    DomainRuleViolation,
    EligibilityEvaluator,
    FormValidationService,
    JsonRuleEvaluator,
    MaterialRuleEngine,
    ServiceMatcher,
    HandoffAccessPolicy,
    HandoffStateMachine,
    AuthorizedCaseQueryService,
    KnowledgeStateMachine,
    PaymentStateMachine,
    ServiceLifecyclePolicy,
)
from app.infrastructure.catalog_seed import DEMO_SERVICES, demo_delivery_contract
from app.main import create_app
from app.security import Principal, TokenCodec, hash_password, mask_personal_text, verify_password
from app.application.coordinators import (
    AdminCoordinator,
    ApplicationCoordinator,
    AuthCoordinator,
    DeliveryCoordinator,
    IdempotencyCoordinator,
    KnowledgeIndexCoordinator,
    ReviewCoordinator,
)
from app.application.ports import BusinessRepositoryPort
from app.boundaries.business_schemas import (
    AppointmentCreateRequest,
    ServiceVersionCreateRequest,
)
from app.database import Database
from app.errors import (
    AuthenticationRequired,
    BusinessValidationError,
    ConflictError,
    DependencyUnavailable,
    PermissionDenied,
    ResourceNotFound,
)
from app.infrastructure.document_parser import LocalKnowledgeParser
from app.infrastructure.records import (
    ApplicationRecord,
    GovernmentServiceRecord,
    KnowledgeIndexJobRecord,
    ReviewTaskRecord,
    ServiceVersionRecord,
    ServiceWindowRecord,
)
from app.infrastructure.repositories import BusinessRepository
from app.infrastructure.runtime import BusinessRuntime
from app.infrastructure.object_store import InMemoryObjectStore
from app.infrastructure.providers import (
    DemoDeliveryProvider,
    DemoFaceVerificationProvider,
    DemoPaymentProvider,
    DemoProviderDisabled,
    DemoSmsProvider,
)
from app.models import ChatMessage, ChatSession
from app.services import AppServices


def _admin_principal() -> Principal:
    return Principal(
        account_id=uuid4(), username="admin", display_name="管理员",
        role=Role.ADMIN, applicant_type=None, token_version=0,
    )


def test_application_and_service_state_machines_reject_skips() -> None:
    applications = ApplicationStateMachine()
    applications.require(ApplicationStatus.DRAFT, ApplicationStatus.SUBMITTED)
    applications.require(ApplicationStatus.IN_REVIEW, ApplicationStatus.NEEDS_SUPPLEMENT)
    with pytest.raises(DomainRuleViolation):
        applications.require(ApplicationStatus.DRAFT, ApplicationStatus.COMPLETED)

    services = ServiceLifecyclePolicy()
    services.require(ServiceStatus.PUBLISHED, ServiceStatus.SUSPENDED)
    services.require(ServiceStatus.SUSPENDED, ServiceStatus.PUBLISHED)
    with pytest.raises(DomainRuleViolation):
        services.require(ServiceStatus.RETIRED, ServiceStatus.PUBLISHED)


def test_json_rule_dsl_matches_mock_contract_and_never_executes_unknown_ops() -> None:
    evaluator = JsonRuleEvaluator()
    rule = {
        "all": [
            {"eq": ["business.registration_status", "ACTIVE"]},
            {"exists": ["fund.contribution_base"]},
            {"gte": ["fund.contribution_ratio", 0.05]},
            {"lte": ["fund.contribution_ratio", 0.12]},
        ]
    }
    facts = {
        "business": {"registration_status": "ACTIVE"},
        "fund": {"contribution_base": 5000, "contribution_ratio": 0.08},
    }
    assert evaluator.evaluate(rule, facts) is True
    assert evaluator.evaluate(rule, {"business": {"registration_status": "ACTIVE"}}) is None
    with pytest.raises(DomainRuleViolation):
        evaluator.evaluate({"python": "__import__('os')"}, facts)


@pytest.mark.parametrize(
    "rule",
    [
        {"eq": ["field", 1], "ne": ["field", 2]},
        {"eq": ["bad field", 1]},
        {"in": ["field", 123]},
        {"lt": ["field", "10"]},
        {"gte": ["field", True]},
        {"all": {"eq": ["field", 1]}},
        {"any": []},
        {"not": [{"eq": ["field", 1]}]},
        {"exists": ["field", "yes"]},
    ],
)
def test_json_rule_static_validation_rejects_malformed_tree(rule: dict[str, object]) -> None:
    with pytest.raises(DomainRuleViolation):
        JsonRuleEvaluator().validate(rule)


def test_admin_rule_validation_maps_malformed_dsl_to_business_422_error() -> None:
    coordinator = AdminCoordinator(object(), object(), object())  # type: ignore[arg-type]
    with pytest.raises(BusinessValidationError) as error:
        coordinator.validate_rules(
            {"eligibility_rules": [{"rule": {"in": ["person.type", 123]}}]}
        )
    assert error.value.status_code == 422


@pytest.mark.parametrize(
    "overrides",
    [
        {"materials": [{}]},
        {"process_steps": [{}]},
        {
            "materials": [
                {"code": "same", "name": "材料一"},
                {"code": "same", "name": "材料二"},
            ]
        },
        {
            "process_steps": [
                {"order": 1, "code": "ONE", "title": "第一步"},
                {"order": 1, "code": "TWO", "title": "第二步"},
            ]
        },
        {"requires_appointment": True, "appointment_supported": False},
    ],
)
def test_nested_service_version_schema_rejects_inputs_that_would_reach_500(
    overrides: dict[str, object],
) -> None:
    payload: dict[str, object] = {"title": "演示事项", "summary": "演示说明"}
    payload.update(overrides)
    with pytest.raises(ValidationError):
        ServiceVersionCreateRequest.model_validate(payload)


def test_service_version_schema_normalizes_compact_rules_and_step_defaults() -> None:
    payload = ServiceVersionCreateRequest.model_validate(
        {
            "title": "演示事项",
            "summary": "演示说明",
            "eligibility_rules": [{"eq": ["person.type", "INDIVIDUAL"]}],
            "process_steps": [{"title": "提交申请"}],
        }
    ).model_dump(mode="json")
    assert payload["eligibility_rules"][0]["rule"] == {
        "eq": ["person.type", "INDIVIDUAL"]
    }
    assert payload["process_steps"][0]["order"] == 1
    assert payload["process_steps"][0]["code"] == "STEP_1"


def test_eligibility_material_and_form_policies_return_explainable_results() -> None:
    eligibility = EligibilityEvaluator().evaluate(
        [({"eq": ["operator.authorized", True]}, "缺少经办授权")],
        {"operator": {}},
    )
    assert eligibility.outcome == "NEEDS_INFORMATION"
    assert eligibility.missing_fields == ("缺少经办授权",)

    requirement = MaterialRequirement(
        id=uuid4(), service_version_id=uuid4(), code="lc-3", name="集体合同说明",
        required=False, condition={"eq": ["contract.type", "COLLECTIVE"]},
    )
    decision = MaterialRuleEngine().classify([requirement], {"contract": {"type": "COLLECTIVE"}})[0]
    assert decision.category == "CONDITIONAL_REQUIRED"
    errors = FormValidationService().validate(
        {"required": ["name"], "properties": {"name": {"type": "string"}}},
        {"name": 123},
    )
    assert errors == {"name": "字段类型应为 string"}


def test_password_jwt_and_masking_security_contract() -> None:
    encoded = hash_password("DemoPassword!2026")
    assert verify_password("DemoPassword!2026", encoded)
    assert not verify_password("wrong", encoded)

    principal = Principal(
        account_id=uuid4(), username="demo", display_name="演示用户",
        role=Role.CITIZEN, applicant_type=ApplicantType.INDIVIDUAL,
        token_version=3,
    )
    codec = TokenCodec("test-signing-key", 15)
    token, _ = codec.issue_access_token(principal)
    assert codec.decode_access_token(token)["ver"] == 3
    with pytest.raises(jwt.InvalidTokenError):
        TokenCodec("different-key", 15).decode_access_token(token)
    assert "演示大道" not in mask_personal_text("演示大道100号")


def test_catalog_seed_covers_six_mock_ids_and_representative_rules() -> None:
    assert [item["external_item_id"] for item in DEMO_SERVICES] == list(range(1001, 1007))
    by_id = {item["external_item_id"]: item for item in DEMO_SERVICES}
    assert by_id[1001]["materials"][1]["required"] is True
    assert by_id[1001]["requires_appointment"] is False
    assert by_id[1002]["fee_cents"] == 4000
    assert by_id[1005]["materials"][2]["condition"] == {"eq": ["contract.type", "COLLECTIVE"]}
    assert by_id[1006]["fee_required"] is True
    assert by_id[1006]["fee_calculation"]
    assert demo_delivery_contract(1002, True)["mail_supported"] is True
    assert demo_delivery_contract(1005, True) == {
        "supported": True,
        "options": ["DIGITAL_RESULT"],
        "mail_supported": False,
        "demo_mail_supported": False,
    }


def test_delivery_contract_respects_internal_version_switch_and_provider_capability() -> None:
    assert demo_delivery_contract(1002, True)["mail_supported"] is True
    assert demo_delivery_contract(1005, True) == {
        "supported": True,
        "options": ["DIGITAL_RESULT"],
        "mail_supported": False,
        "demo_mail_supported": False,
    }
    assert demo_delivery_contract(1002, False)["supported"] is False


def test_service_matcher_surfaces_generic_social_security_ambiguity() -> None:
    services = [
        {"id": uuid4(), "title": "社会保障卡申领", "summary": ""},
        {"id": uuid4(), "title": "企业社会保险登记", "summary": ""},
    ]
    items, ambiguous = ServiceMatcher().match("社保怎么办", services)
    assert ambiguous is True
    assert len(items) == 2
    items, ambiguous = ServiceMatcher().match("企业社保怎么办", services)
    assert ambiguous is False
    assert items[0]["title"] == "企业社会保险登记"


def test_handoff_policy_blocks_cross_department_and_other_assignee() -> None:
    policy = HandoffAccessPolicy()
    policy.require_staff_access("staff-a", "dept-a", None, None, claiming=True)
    with pytest.raises(DomainRuleViolation):
        policy.require_staff_access("staff-a", "dept-a", "dept-b", None, claiming=True)
    with pytest.raises(DomainRuleViolation):
        policy.require_staff_access("staff-a", "dept-a", "dept-a", "staff-b", claiming=True)
    with pytest.raises(DomainRuleViolation):
        policy.require_staff_access("staff-a", "dept-a", "dept-a", None, claiming=False)


def test_authorized_case_query_policy_matrix() -> None:
    policy = AuthorizedCaseQueryService()
    assert policy.may_view(Role.ADMIN, "admin", "owner")
    assert policy.may_view(Role.CITIZEN, "owner", "owner")
    assert not policy.may_view(Role.CITIZEN, "other", "owner")
    assert policy.may_view(Role.STAFF, "staff", "owner", same_department=True)
    assert not policy.may_view(
        Role.STAFF, "staff", "owner", same_department=False
    )


@pytest.mark.asyncio
async def test_review_coordinator_applies_assignment_policy_before_mutation() -> None:
    staff_department = uuid4()
    other_department = uuid4()

    class Repository:
        async def get_review_task_department(self, _task_id: object) -> object:
            return other_department

    class Idempotency:
        async def execute(self, *_: object) -> object:
            raise AssertionError("cross-department task must not reach mutation")

    coordinator = ReviewCoordinator(
        Repository(), Idempotency()  # type: ignore[arg-type]
    )
    principal = Principal(
        account_id=uuid4(), username="staff", display_name="工作人员",
        role=Role.STAFF, applicant_type=None, token_version=0,
        department_id=staff_department,
    )
    with pytest.raises(PermissionDenied):
        await coordinator.claim(principal, uuid4(), "claim-key")


def test_terminal_handoff_appointment_and_delivery_states_cannot_revive() -> None:
    with pytest.raises(DomainRuleViolation):
        HandoffStateMachine().require(
            HandoffStatus.RESOLVED, HandoffStatus.IN_PROGRESS
        )
    with pytest.raises(DomainRuleViolation):
        AppointmentStateMachine().require(
            AppointmentStatus.COMPLETED, AppointmentStatus.BOOKED
        )
    delivery = DeliveryStateMachine()
    delivery.require(DeliveryStatus.ACCEPTED, DeliveryStatus.DISPATCHED)
    delivery.require(DeliveryStatus.DISPATCHED, DeliveryStatus.DELIVERED)
    with pytest.raises(DomainRuleViolation):
        delivery.require(DeliveryStatus.DELIVERED, DeliveryStatus.DISPATCHED)


def test_openapi_exposes_post_eligibility_sse_and_idempotency_headers() -> None:
    schema = create_app().openapi()
    eligibility = schema["paths"]["/api/v1/services/{service_id}/eligibility"]
    assert set(eligibility) == {"post"}
    assert "requestBody" in eligibility["post"]
    assert "post" in schema["paths"]["/api/v1/chat/stream"]
    submit_parameters = schema["paths"]["/api/v1/applications/{application_id}/submit"]["post"]["parameters"]
    assert any(item["name"] == "Idempotency-Key" and item["required"] for item in submit_parameters)


@pytest.mark.asyncio
async def test_material_upload_rejects_spoofed_content_before_storage() -> None:
    class Repository:
        async def add_material(self, *args: object) -> dict[str, object]:
            raise AssertionError("repository must not be called")

    coordinator = ApplicationCoordinator(
        Repository(), InMemoryObjectStore(), object(), 10 * 1024 * 1024  # type: ignore[arg-type]
    )
    principal = Principal(
        account_id=uuid4(), username="citizen", display_name="演示群众",
        role=Role.CITIZEN, applicant_type=ApplicantType.INDIVIDUAL,
        token_version=0,
    )
    with pytest.raises(BusinessValidationError):
        await coordinator.upload_material(
            principal, uuid4(), "identity", "fake.png", "image/png", b"not-a-png"
        )


@pytest.mark.asyncio
async def test_concurrent_idempotency_executes_side_effect_once() -> None:
    class Repository:
        value: dict[str, object] | None = None

        async def get_idempotent(self, *_: object) -> dict[str, object] | None:
            return self.value

        async def store_idempotent(
            self, _actor: object, _scope: object, _key: object,
            _digest: object, response: dict[str, object],
        ) -> dict[str, object]:
            self.value = response
            return response

    repository = Repository()
    coordinator = IdempotencyCoordinator(repository)  # type: ignore[arg-type]
    executions = 0

    async def operation() -> dict[str, object]:
        nonlocal executions
        executions += 1
        await asyncio.sleep(0.01)
        return {"id": "one"}

    actor = uuid4()
    first, second = await asyncio.gather(
        coordinator.execute(actor, "submit", "same-key", {"v": 1}, operation),
        coordinator.execute(actor, "submit", "same-key", {"v": 1}, operation),
    )
    assert first == second == {"id": "one"}
    assert executions == 1
    assert coordinator._locks == {}


@pytest.mark.asyncio
async def test_owned_chat_rejects_anonymous_and_cross_user_before_message_write() -> None:
    owner_id = uuid4()
    owned = ChatSession(id=uuid4(), owner_account_id=owner_id)

    class Session:
        added: list[object] = []

        async def get(self, *_: object, **__: object) -> ChatSession:
            return owned

        def add(self, value: object) -> None:
            self.added.append(value)

    session = Session()

    class Transaction:
        async def __aenter__(self) -> Session:
            return session

        async def __aexit__(self, *_: object) -> None:
            return None

    class Sessions:
        def begin(self) -> Transaction:
            return Transaction()

    database = object.__new__(Database)
    database.sessions = Sessions()  # type: ignore[assignment]
    request_id = uuid4()

    with pytest.raises(AuthenticationRequired):
        await database.save_user_message(owned.id, request_id, "anonymous", None)
    with pytest.raises(PermissionDenied):
        await database.save_user_message(owned.id, request_id, "other", uuid4())
    assert not any(isinstance(item, ChatMessage) for item in session.added)


@pytest.mark.asyncio
async def test_chat_history_conceals_cross_owner_and_rejects_unowned_context() -> None:
    owner_id = uuid4()
    owned = ChatSession(id=uuid4(), owner_account_id=owner_id)

    class Session:
        async def get(self, *_: object, **__: object) -> ChatSession:
            return owned

    class Context:
        async def __aenter__(self) -> Session:
            return Session()

        async def __aexit__(self, *_: object) -> None:
            return None

    class Sessions:
        def __call__(self) -> Context:
            return Context()

    database = object.__new__(Database)
    database.sessions = Sessions()  # type: ignore[assignment]

    with pytest.raises(ResourceNotFound):
        await database.list_messages_authorized(
            owned.id, uuid4(), limit=50
        )
    with pytest.raises(AuthenticationRequired):
        await database.load_recent_history(owned.id, None, limit=8)
    with pytest.raises(PermissionDenied):
        await database.load_recent_history(owned.id, uuid4(), limit=8)


@pytest.mark.asyncio
async def test_legacy_anonymous_chat_stays_anonymous_and_authenticated_chat_starts_owned() -> None:
    anonymous = ChatSession(id=uuid4(), owner_account_id=None)

    class Session:
        def __init__(self, current: ChatSession | None) -> None:
            self.current = current
            self.added: list[object] = []

        async def get(self, *_: object, **__: object) -> ChatSession | None:
            return self.current

        async def flush(self) -> None:
            return None

        def add(self, value: object) -> None:
            self.added.append(value)
            if isinstance(value, ChatSession):
                self.current = value

    class Transaction:
        def __init__(self, session: Session) -> None:
            self.session = session

        async def __aenter__(self) -> Session:
            return self.session

        async def __aexit__(self, *_: object) -> None:
            return None

    class Sessions:
        def __init__(self, session: Session) -> None:
            self.session = session

        def begin(self) -> Transaction:
            return Transaction(self.session)

    database = object.__new__(Database)
    anonymous_session = Session(anonymous)
    database.sessions = Sessions(anonymous_session)  # type: ignore[assignment]
    await database.save_user_message(anonymous.id, uuid4(), "匿名继续咨询", None)
    assert anonymous.owner_account_id is None
    assert sum(isinstance(item, ChatMessage) for item in anonymous_session.added) == 1

    before = len(anonymous_session.added)
    with pytest.raises(ConflictError) as error:
        await database.save_user_message(
            anonymous.id, uuid4(), "登录后不能接管", uuid4()
        )
    assert error.value.code == "anonymous_session_not_claimable"
    assert len(anonymous_session.added) == before
    assert anonymous.owner_account_id is None

    owner_id = uuid4()
    new_session = Session(None)
    database.sessions = Sessions(new_session)  # type: ignore[assignment]
    new_id = uuid4()
    await database.save_user_message(new_id, uuid4(), "登录后新咨询", owner_id)
    assert new_session.current is not None
    assert new_session.current.owner_account_id == owner_id
    assert sum(isinstance(item, ChatMessage) for item in new_session.added) == 1


@pytest.mark.asyncio
async def test_first_chat_messages_are_serialized_by_session_advisory_lock() -> None:
    class Shared:
        def __init__(self) -> None:
            self.lock = asyncio.Lock()
            self.current: ChatSession | None = None
            self.messages: list[ChatMessage] = []
            self.lock_names: list[str] = []

    class Session:
        def __init__(self, shared: Shared) -> None:
            self.shared = shared
            self.locked = False

        async def execute(
            self, _statement: object, parameters: dict[str, str]
        ) -> None:
            await self.shared.lock.acquire()
            self.locked = True
            self.shared.lock_names.append(parameters["lock_name"])

        async def get(self, *_: object, **__: object) -> ChatSession | None:
            return self.shared.current

        async def flush(self) -> None:
            # Widen the old missing-row race; the advisory lock must still keep
            # the second transaction from observing an absent session.
            await asyncio.sleep(0.005)

        def add(self, value: object) -> None:
            if isinstance(value, ChatSession):
                self.shared.current = value
            elif isinstance(value, ChatMessage):
                self.shared.messages.append(value)

    class Transaction:
        def __init__(self, shared: Shared) -> None:
            self.session = Session(shared)

        async def __aenter__(self) -> Session:
            return self.session

        async def __aexit__(self, *_: object) -> None:
            if self.session.locked:
                self.session.shared.lock.release()

    class Sessions:
        def __init__(self, shared: Shared) -> None:
            self.shared = shared

        def begin(self) -> Transaction:
            return Transaction(self.shared)

    async def database_for(shared: Shared) -> Database:
        database = object.__new__(Database)
        database.engine = SimpleNamespace(
            dialect=SimpleNamespace(name="postgresql")
        )
        database.sessions = Sessions(shared)  # type: ignore[assignment]
        return database

    session_id = uuid4()
    owner = uuid4()
    same_owner = Shared()
    database = await database_for(same_owner)
    await asyncio.gather(
        database.save_user_message(
            session_id, uuid4(), "first", owner
        ),
        database.save_user_message(
            session_id, uuid4(), "second", owner
        ),
    )
    assert same_owner.current is not None
    assert same_owner.current.owner_account_id == owner
    assert len(same_owner.messages) == 2
    assert len(same_owner.lock_names) == 2
    assert len(set(same_owner.lock_names)) == 1

    cross_owner = Shared()
    database = await database_for(cross_owner)
    owner_a, owner_b = uuid4(), uuid4()
    results = await asyncio.gather(
        database.save_user_message(session_id, uuid4(), "owner-a", owner_a),
        database.save_user_message(session_id, uuid4(), "owner-b", owner_b),
        return_exceptions=True,
    )
    assert sum(isinstance(result, UUID) for result in results) == 1
    assert sum(isinstance(result, PermissionDenied) for result in results) == 1
    assert cross_owner.current is not None
    assert cross_owner.current.owner_account_id in {owner_a, owner_b}
    assert len(cross_owner.messages) == 1


@pytest.mark.asyncio
async def test_staff_cannot_read_draft_even_if_a_stale_task_were_present() -> None:
    record = ApplicationRecord(
        id=uuid4(),
        applicant_id=uuid4(),
        service_id=uuid4(),
        service_version_id=uuid4(),
        status=ApplicationStatus.DRAFT.value,
        form_data={},
        version=1,
    )

    class Session:
        async def scalar(self, *_: object, **__: object) -> object:
            raise AssertionError("DRAFT must be denied before querying review tasks")

    repository = object.__new__(BusinessRepository)
    with pytest.raises(ResourceNotFound):
        await repository._require_application_access(  # noqa: SLF001
            Session(), record, uuid4(), Role.STAFF, uuid4()  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_withdrawal_closes_active_review_tasks_in_same_unit_of_work() -> None:
    actor_id = uuid4()
    application = ApplicationRecord(
        id=uuid4(), applicant_id=actor_id, service_id=uuid4(),
        service_version_id=uuid4(), status=ApplicationStatus.SUBMITTED.value,
        form_data={}, version=2,
    )
    task = ReviewTaskRecord(
        id=uuid4(), application_id=application.id, department_id=uuid4(),
        status="PENDING",
    )

    class Session:
        async def get(self, model: object, _identifier: object, **_: object) -> object:
            if model is ApplicationRecord:
                return application
            raise AssertionError(model)

        async def scalar(self, _statement: object) -> ReviewTaskRecord:
            return task

        async def execute(self, _statement: object) -> SimpleNamespace:
            task.status = "CANCELLED"
            task.decision = ApplicationStatus.WITHDRAWN.value
            return SimpleNamespace()

        async def flush(self) -> None:
            return None

        async def refresh(self, _record: object) -> None:
            return None

    session = Session()

    @asynccontextmanager
    async def transaction():
        yield session

    async def noop(*_: object, **__: object) -> None:
        return None

    repository = object.__new__(BusinessRepository)
    repository._application_states = ApplicationStateMachine()  # noqa: SLF001
    repository._transaction = transaction  # type: ignore[method-assign]
    repository._event = noop  # type: ignore[method-assign]
    repository._audit = noop  # type: ignore[method-assign]

    result = await repository.transition_application(
        application.id, actor_id, Role.CITIZEN,
        ApplicationStatus.WITHDRAWN, 2, "群众撤回",
    )

    assert result["status"] == ApplicationStatus.WITHDRAWN.value
    assert task.status == "CANCELLED"
    assert task.decision == ApplicationStatus.WITHDRAWN.value


@pytest.mark.asyncio
async def test_claim_rechecks_application_state_and_rejects_zombie_task() -> None:
    application = ApplicationRecord(
        id=uuid4(), applicant_id=uuid4(), service_id=uuid4(),
        service_version_id=uuid4(), status=ApplicationStatus.WITHDRAWN.value,
        form_data={}, version=3,
    )
    department_id = uuid4()
    task = ReviewTaskRecord(
        id=uuid4(), application_id=application.id,
        department_id=department_id, status="PENDING",
    )

    class Session:
        async def get(self, model: object, _identifier: object, **_: object) -> object:
            return task if model is ReviewTaskRecord else application

    session = Session()

    @asynccontextmanager
    async def transaction():
        yield session

    repository = object.__new__(BusinessRepository)
    repository._transaction = transaction  # type: ignore[method-assign]
    with pytest.raises(ConflictError) as error:
        await repository.claim_task(task.id, uuid4(), department_id)
    assert error.value.code == "application_not_reviewable"
    assert task.status == "PENDING" and task.assignee_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("service_status", "window_active", "window_matches", "error_type"),
    [
        (ServiceStatus.SUSPENDED.value, True, True, ConflictError),
        (ServiceStatus.RETIRED.value, True, True, ConflictError),
        (ServiceStatus.PUBLISHED.value, False, True, ResourceNotFound),
        (ServiceStatus.PUBLISHED.value, True, False, ResourceNotFound),
    ],
)
async def test_appointment_rejects_unavailable_service_or_window(
    service_status: str,
    window_active: bool,
    window_matches: bool,
    error_type: type[Exception],
) -> None:
    department_id = uuid4()
    window_id = uuid4()
    service = GovernmentServiceRecord(
        id=uuid4(), code="TEST-SERVICE", department_id=department_id,
        window_id=window_id if window_matches else uuid4(),
        applicant_type=ApplicantType.INDIVIDUAL.value,
        status=service_status, current_version_id=uuid4(),
    )
    window = ServiceWindowRecord(
        id=window_id, department_id=department_id, code="TEST-WINDOW",
        name="演示窗口", address="演示地址", latitude=1, longitude=1,
        opening_hours="工作日", capacity_per_slot=1, active=window_active,
    )
    version = ServiceVersionRecord(
        id=service.current_version_id, service_id=service.id, version=1,
        title="演示事项", summary="演示", form_schema={}, fee_cents=0,
        fee_required=False, appointment_supported=True,
        requires_appointment=False, requires_verification=False,
        delivery_supported=False, immutable=True,
    )

    class Session:
        async def get(self, model: object, _identifier: object, **_: object) -> object:
            return {
                GovernmentServiceRecord: service,
                ServiceWindowRecord: window,
                ServiceVersionRecord: version,
            }[model]

    @asynccontextmanager
    async def transaction():
        yield Session()

    repository = object.__new__(BusinessRepository)
    repository._transaction = transaction  # type: ignore[method-assign]
    with pytest.raises(error_type):
        await repository.create_appointment(
            uuid4(), service.id, window.id,
            datetime.now(timezone.utc) + timedelta(days=1),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("broken.txt", b"\xff\xfe\xfa"),
        ("broken.pdf", b"%PDF-1.4\nbroken"),
        ("broken.docx", b"PK\x03\x04broken"),
    ],
)
async def test_invalid_knowledge_files_return_422_before_storage(
    filename: str, content: bytes
) -> None:
    class Repository:
        async def create_knowledge_records(self, *_: object) -> object:
            raise AssertionError("invalid content must not reach PostgreSQL")

    class Milvus:
        async def index_chunks(self, *_: object) -> None:
            raise AssertionError("invalid content must not reach Milvus")

    store = InMemoryObjectStore()
    coordinator = KnowledgeIndexCoordinator(
        Repository(), store, Milvus(), LocalKnowledgeParser(), object()  # type: ignore[arg-type]
    )
    principal = Principal(
        account_id=uuid4(), username="admin", display_name="管理员",
        role=Role.ADMIN, applicant_type=None, token_version=0,
    )

    with pytest.raises(BusinessValidationError) as error:
        await coordinator.upload(
            principal, filename, "application/octet-stream", content,
            "坏文件", "demo://invalid",
        )
    assert error.value.status_code == 422
    assert error.value.message == "知识文件格式无效或无法解析"
    assert store.objects == {}


@pytest.mark.asyncio
async def test_oversized_knowledge_file_returns_422_without_orphans() -> None:
    store = InMemoryObjectStore()
    coordinator = KnowledgeIndexCoordinator(
        object(), store, object(), LocalKnowledgeParser(), object()  # type: ignore[arg-type]
    )
    principal = Principal(
        account_id=uuid4(), username="admin", display_name="管理员",
        role=Role.ADMIN, applicant_type=None, token_version=0,
    )
    oversized = b"x" * (coordinator.max_knowledge_bytes + 1)
    with pytest.raises(BusinessValidationError) as error:
        await coordinator.upload(
            principal, "too-large.txt", "text/plain", oversized,
            "超限文件", "demo://oversized",
        )
    assert error.value.status_code == 422
    assert store.objects == {}


def test_cancel_and_archive_state_transitions_are_terminal() -> None:
    handoff = HandoffStateMachine()
    handoff.require(HandoffStatus.QUEUED, HandoffStatus.CANCELLED)
    payment = PaymentStateMachine()
    payment.require(PaymentStatus.CREATED, PaymentStatus.CANCELLED)
    payment.require(PaymentStatus.PENDING, PaymentStatus.CANCELLED)
    payment.require(PaymentStatus.FAILED, PaymentStatus.CANCELLED)
    knowledge = KnowledgeStateMachine()
    knowledge.require(KnowledgeStatus.ACTIVE, KnowledgeStatus.ARCHIVED)

    with pytest.raises(DomainRuleViolation):
        handoff.require(HandoffStatus.CANCELLED, HandoffStatus.IN_PROGRESS)
    with pytest.raises(DomainRuleViolation):
        payment.require(PaymentStatus.SUCCEEDED, PaymentStatus.CANCELLED)
    with pytest.raises(DomainRuleViolation):
        knowledge.require(KnowledgeStatus.ARCHIVED, KnowledgeStatus.ACTIVE)


def test_cancel_archive_endpoints_require_idempotency_key() -> None:
    paths = create_app().openapi()["paths"]
    operations = (
        paths["/api/v1/consultations/handoffs/{ticket_id}/cancel"]["post"],
        paths["/api/v1/payments/{payment_id}/cancel"]["post"],
        paths["/api/v1/deliveries/{delivery_id}/cancel"]["post"],
        paths["/api/v1/admin/knowledge/{job_id}/archive"]["post"],
    )
    for operation in operations:
        assert any(
            parameter["name"] == "Idempotency-Key" and parameter["required"]
            for parameter in operation["parameters"]
        )


def test_appointment_requires_timezone_and_normalizes_to_utc() -> None:
    with pytest.raises(ValidationError):
        AppointmentCreateRequest(
            service_id=uuid4(), window_id=uuid4(),
            slot_start="2030-01-01T09:00:00",
        )
    request = AppointmentCreateRequest(
        service_id=uuid4(), window_id=uuid4(),
        slot_start="2030-01-01T09:00:00+08:00",
    )
    assert request.slot_start.isoformat() == "2030-01-01T01:00:00+00:00"


@pytest.mark.parametrize(
    "form_schema",
    ({"required": 123}, {"properties": []}),
)
def test_admin_rejects_malformed_form_schema(form_schema: object) -> None:
    with pytest.raises(ValidationError):
        ServiceVersionCreateRequest(
            title="错误表单", summary="演示", form_schema=form_schema,
        )


@pytest.mark.parametrize(
    "fee_values",
    (
        {"fee_required": True, "fee_cents": 0},
        {"fee_required": False, "fee_cents": 100},
        {"fee_required": False, "fee_calculation": "unsupported"},
        {
            "fee_required": True, "fee_cents": 100,
            "fee_calculation": "DEMO_CONTRIBUTION_BASE_TIMES_RATIO",
        },
    ),
)
def test_admin_rejects_inconsistent_fee_contract(
    fee_values: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        ServiceVersionCreateRequest(
            title="费用错误事项", summary="演示", **fee_values
        )


def test_json_schema_integer_and_number_reject_boolean() -> None:
    validator = FormValidationService()
    for field_type in ("integer", "number"):
        errors = validator.validate(
            {"type": "object", "properties": {"value": {"type": field_type}}},
            {"value": True},
        )
        assert errors == {"value": f"字段类型应为 {field_type}"}


@pytest.mark.asyncio
async def test_material_requirement_type_is_checked_before_object_storage() -> None:
    calls: list[tuple[str, str]] = []

    class Repository:
        async def preflight_material_upload(
            self, _application_id: object, _account_id: object,
            requirement_code: str, content_type: str,
        ) -> None:
            calls.append((requirement_code, content_type))
            raise BusinessValidationError("该材料仅支持 application/pdf")

    store = InMemoryObjectStore()
    coordinator = ApplicationCoordinator(
        Repository(), store, object(), 10 * 1024 * 1024  # type: ignore[arg-type]
    )
    principal = Principal(
        account_id=uuid4(), username="citizen", display_name="群众",
        role=Role.CITIZEN, applicant_type=ApplicantType.INDIVIDUAL,
        token_version=0,
    )
    jpeg = b"\xff\xd8\xff\xe0" + b"demo"
    with pytest.raises(BusinessValidationError):
        await coordinator.upload_material(
            principal, uuid4(), "ONLY_PDF", "photo.jpg", "image/jpeg", jpeg
        )
    assert calls == [("ONLY_PDF", "image/jpeg")]
    assert store.objects == {}


@pytest.mark.asyncio
async def test_delivery_preflight_skips_duplicate_provider_side_effect() -> None:
    existing = {"id": uuid4(), "status": "ACCEPTED"}

    class Repository:
        async def preflight_delivery(self, *_: object) -> dict[str, object]:
            return existing

        async def create_delivery(self, *_: object) -> dict[str, object]:
            raise AssertionError("existing order must be returned")

    class Provider:
        async def create(self) -> dict[str, object]:
            raise AssertionError("provider must run only after locked preflight")

    class Security:
        def mask_personal_text(self, value: str) -> str:
            return value

    class Idempotency:
        async def execute(self, *args: object) -> dict[str, object]:
            return await args[-1]()  # type: ignore[operator]

    coordinator = DeliveryCoordinator(
        Repository(), Provider(), Security(), Idempotency()  # type: ignore[arg-type]
    )
    principal = Principal(
        account_id=uuid4(), username="citizen", display_name="群众",
        role=Role.CITIZEN, applicant_type=ApplicantType.INDIVIDUAL,
        token_version=0,
    )
    assert await coordinator.create(
        principal, uuid4(), "张某", "演示地址", "delivery-key"
    ) == existing


@pytest.mark.asyncio
async def test_concurrent_duplicate_knowledge_upload_keeps_canonical_object() -> None:
    class Repository:
        def __init__(self) -> None:
            self.lock = asyncio.Lock()
            self.keys: list[str] = []

        async def create_knowledge_records(
            self, _actor: object, _document: object, _title: object,
            _source: object, _content: object, object_key: str,
            _chunks: object,
        ) -> tuple[object, list[dict[str, str]], bool, str]:
            async with self.lock:
                self.keys.append(object_key)
                retained = len(self.keys) == 1
                return (
                    uuid4(),
                    [{
                        "id": str(uuid4()), "title": "demo",
                        "content": "demo", "source": "demo://same",
                    }],
                    retained,
                    "INDEXING",
                )

        async def finish_knowledge_job(self, *_: object) -> None:
            return None

    class Parser:
        def extract(self, _extension: str, _content: bytes) -> str:
            return "相同的公开演示知识文本"

    class Milvus:
        async def index_chunks(self, _rows: object) -> None:
            await asyncio.sleep(0)

        async def activate_chunks(self, _rows: object) -> None:
            await asyncio.sleep(0)

    repository = Repository()
    store = InMemoryObjectStore()
    coordinator = KnowledgeIndexCoordinator(
        repository, store, Milvus(), Parser(), object()  # type: ignore[arg-type]
    )
    content = b"same public demo content"
    await asyncio.gather(
        coordinator.upload(
            _admin_principal(), "same.txt", "text/plain", content,
            "公开知识", "demo://same",
        ),
        coordinator.upload(
            _admin_principal(), "same.txt", "text/plain", content,
            "公开知识", "demo://same",
        ),
    )

    assert len(repository.keys) == 2
    assert repository.keys[0] != repository.keys[1]
    assert list(store.objects) == [(store.knowledge_bucket, repository.keys[0])]


@pytest.mark.asyncio
async def test_failed_knowledge_retry_commits_failure_marker_before_409() -> None:
    job_id = uuid4()

    class Repository:
        finished: tuple[object, bool, str | None] | None = None

        async def prepare_knowledge_retry(self, *_: object) -> list[dict[str, str]]:
            return [{"id": "chunk", "content": "demo"}]

        async def finish_knowledge_job(
            self, identifier: object, success: bool, error: str | None = None
        ) -> None:
            self.finished = (identifier, success, error)

    class Milvus:
        async def index_chunks(self, _chunks: object) -> None:
            raise RuntimeError("transient")

    class Idempotency:
        committed: dict[str, object] | None = None

        async def execute(self, *args: object) -> dict[str, object]:
            self.committed = await args[-1]()  # type: ignore[operator]
            return self.committed

    repository = Repository()
    idempotency = Idempotency()
    coordinator = KnowledgeIndexCoordinator(
        repository, object(), Milvus(), object(), idempotency  # type: ignore[arg-type]
    )
    with pytest.raises(ConflictError) as error:
        await coordinator.retry(_admin_principal(), job_id, "retry-key")

    assert error.value.code == "knowledge_index_failed"
    assert repository.finished == (job_id, False, "RuntimeError")
    assert idempotency.committed is not None
    assert idempotency.committed["status"] == "INDEX_FAILED"
    assert idempotency.committed["_index_failed"] is True


@pytest.mark.asyncio
async def test_startup_recovers_even_fresh_indexing_job_for_retry() -> None:
    job = KnowledgeIndexJobRecord(
        id=uuid4(), document_id="admin-fresh-crash",
        status="INDEXING", attempts=1, last_error=None,
        updated_at=datetime.now(timezone.utc),
    )

    class Session:
        updates = 0

        async def scalars(self, _statement: object) -> SimpleNamespace:
            return SimpleNamespace(all=lambda: [job])

        async def scalar(self, _statement: object) -> None:
            return None

        async def execute(self, _statement: object) -> None:
            self.updates += 1

    session = Session()

    class Begin:
        async def __aenter__(self) -> Session:
            return session

        async def __aexit__(self, *_: object) -> None:
            return None

    class Sessions:
        def begin(self) -> Begin:
            return Begin()

    repository = object.__new__(BusinessRepository)
    repository.sessions = Sessions()

    recovered = await repository.recover_stale_knowledge_jobs()

    assert recovered == 1
    assert job.status == "INDEX_FAILED"
    assert job.last_error == "stale_indexing_recovered"
    assert session.updates == 1


@pytest.mark.asyncio
async def test_knowledge_archive_removes_vectors_and_invalidates_public_cache() -> None:
    job_id = uuid4()
    chunk_ids = [str(uuid4()), str(uuid4())]

    class Repository:
        async def archive_knowledge(self, *_: object) -> dict[str, object]:
            return {
                "job_id": job_id, "status": "ARCHIVED",
                "_chunk_ids": chunk_ids,
            }

    class Milvus:
        deleted: list[str] = []

        async def delete_chunks(self, values: list[str]) -> None:
            self.deleted = values

    class Cache:
        invalidations = 0

        async def invalidate_public(self) -> None:
            self.invalidations += 1

    class Idempotency:
        async def execute(self, *args: object) -> dict[str, object]:
            return await args[-1]()  # type: ignore[operator]

    milvus = Milvus()
    cache = Cache()
    coordinator = KnowledgeIndexCoordinator(
        Repository(), object(), milvus, object(), Idempotency(), cache  # type: ignore[arg-type]
    )
    result = await coordinator.archive(_admin_principal(), job_id, "archive-key")

    assert result == {"job_id": job_id, "status": "ARCHIVED"}
    assert milvus.deleted == chunk_ids
    assert cache.invalidations == 1


@pytest.mark.asyncio
async def test_knowledge_archive_vector_failure_is_structured_503() -> None:
    class Repository:
        async def archive_knowledge(self, *_: object) -> dict[str, object]:
            return {"status": "ARCHIVED", "_chunk_ids": [str(uuid4())]}

    class Milvus:
        async def delete_chunks(self, _values: object) -> None:
            raise RuntimeError("unavailable")

    class Idempotency:
        async def execute(self, *args: object) -> dict[str, object]:
            return await args[-1]()  # type: ignore[operator]

    coordinator = KnowledgeIndexCoordinator(
        Repository(), object(), Milvus(), object(), Idempotency()  # type: ignore[arg-type]
    )
    with pytest.raises(DependencyUnavailable) as error:
        await coordinator.archive(_admin_principal(), uuid4(), "archive-key")
    assert error.value.code == "milvus_unavailable"
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_all_disabled_demo_providers_raise_structured_503() -> None:
    operations = (
        DemoSmsProvider(False, "000000").send_code("13900000000", "REGISTER"),
        DemoPaymentProvider(False).pay("success"),
        DemoFaceVerificationProvider(False).verify("pass"),
        DemoDeliveryProvider(False).create(),
    )
    for operation in operations:
        with pytest.raises(DemoProviderDisabled) as error:
            await operation
        assert error.value.status_code == 503
        assert error.value.code == "demo_provider_unavailable"


@pytest.mark.asyncio
async def test_token_issue_is_aborted_when_account_changes_during_login() -> None:
    record = SimpleNamespace(
        id=uuid4(), username="race-user", display_name="并发演示用户",
        password_hash="encoded", role=Role.CITIZEN.value,
        applicant_type=ApplicantType.INDIVIDUAL.value,
        active=True, token_version=7, department_id=None,
    )

    class Repository:
        async def get_account_by_username(self, _username: str) -> object:
            return record

        async def save_refresh_token_if_current(
            self, _account_id: object, expected_version: int,
            _token: str, _expires_at: datetime,
        ) -> None:
            assert expected_version == 7
            record.active = False
            raise AuthenticationRequired("账号状态已变化，请重新登录")

        async def get_account_view(self, _account_id: object) -> dict[str, object]:
            raise AssertionError("failed issuance must not return an account view")

    class Security:
        @staticmethod
        def verify_password(_password: str, _encoded: str) -> bool:
            return True

        @staticmethod
        def issue_access_token(_principal: Principal) -> tuple[str, datetime]:
            return "unreturned-access", datetime.now(timezone.utc) + timedelta(minutes=15)

        @staticmethod
        def new_refresh_token() -> str:
            return "unreturned-refresh"

    coordinator = AuthCoordinator(
        Repository(), Security(), object(), 7, "000000"  # type: ignore[arg-type]
    )
    with pytest.raises(AuthenticationRequired):
        await coordinator.login("race-user", "correct-password")


def test_bce_dependency_direction_is_enforced_by_source_tree() -> None:
    app_root = Path(__file__).resolve().parents[1] / "app"
    domain_forbidden = (
        "from fastapi", "import fastapi", "from sqlalchemy", "import sqlalchemy",
        "from redis", "import redis", "from pymilvus", "import pymilvus",
        "from app.infrastructure", "import app.infrastructure",
    )
    application_forbidden = domain_forbidden + (
        "from app.chat", "import app.chat", "from app.security",
        "import app.security", "from app.schemas", "import app.schemas",
        "import jwt", "from jwt", "import docx",
        "from docx", "import pypdf", "from pypdf",
    )
    for path in (app_root / "domain").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in domain_forbidden), path
    for path in (app_root / "application").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in application_forbidden), path
    boundary_source = (app_root / "boundaries" / "http.py").read_text(
        encoding="utf-8"
    )
    assert ".repository" not in boundary_source

    # HTTP composition must enter the chat use case through the application
    # coordinator, never through the legacy facade or infrastructure adapters.
    for relative_path in ("main.py", "boundaries/http.py"):
        tree = ast.parse((app_root / relative_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "app.chat", relative_path
            if isinstance(node, ast.Call):
                called = node.func
                assert not (
                    isinstance(called, ast.Name) and called.id == "handle_chat"
                ), relative_path
                assert not (
                    isinstance(called, ast.Attribute)
                    and called.attr == "handle_chat"
                ), relative_path


def test_every_coordinator_repository_call_is_declared_by_the_port() -> None:
    app_root = Path(__file__).resolve().parents[1] / "app"
    coordinator_tree = ast.parse(
        (app_root / "application" / "coordinators.py").read_text(
            encoding="utf-8"
        )
    )
    used: set[str] = set()
    for node in ast.walk(coordinator_tree):
        if not isinstance(node, ast.Attribute):
            continue
        owner = node.value
        if (
            isinstance(owner, ast.Attribute)
            and owner.attr == "repository"
            and isinstance(owner.value, ast.Name)
            and owner.value.id == "self"
        ):
            used.add(node.attr)

    declared = {
        name
        for name, member in inspect.getmembers(
            BusinessRepositoryPort, inspect.isfunction
        )
        if not name.startswith("_")
    }
    assert used <= declared, f"repository port missing: {sorted(used - declared)}"

    # Keep the adapter and port call shapes synchronized. Return annotations
    # intentionally remain domain-facing abstractions, but parameter names,
    # kinds and optionality must match the concrete adapter exactly.
    for name in declared:
        assert hasattr(BusinessRepository, name), f"adapter missing port method: {name}"
        port_parameters = [
            (item.name, item.kind, item.default is not inspect.Parameter.empty)
            for item in inspect.signature(
                getattr(BusinessRepositoryPort, name)
            ).parameters.values()
            if item.name != "self"
        ]
        adapter_parameters = [
            (item.name, item.kind, item.default is not inspect.Parameter.empty)
            for item in inspect.signature(
                getattr(BusinessRepository, name)
            ).parameters.values()
            if item.name != "self"
        ]
        assert port_parameters == adapter_parameters, name


@pytest.mark.asyncio
async def test_business_seed_readiness_retries_one_time_failure() -> None:
    class ObjectStore:
        pings = 0

        async def ping(self) -> None:
            self.pings += 1

    class Business:
        def __init__(self) -> None:
            self.object_store = ObjectStore()
            self.starts = 0

        async def startup(self) -> None:
            self.starts += 1

    services = object.__new__(AppServices)
    services.settings = SimpleNamespace(seed_on_startup=True)
    services.business = Business()
    services._seed_failures = {"business"}

    await services._business_ready()

    assert services.business.object_store.pings == 1
    assert services.business.starts == 1
    assert "business" not in services._seed_failures


@pytest.mark.asyncio
async def test_business_runtime_concurrent_startup_hashes_and_seeds_once() -> None:
    class Store:
        ensures = 0

        async def ensure_buckets(self) -> None:
            self.ensures += 1
            await asyncio.sleep(0.005)

    class Repository:
        seeds = 0
        active_lists = 0

        async def seed_demo_catalog(self, *_: object) -> None:
            self.seeds += 1
            await asyncio.sleep(0.005)

        async def list_active_knowledge_chunks(self) -> list[dict[str, str]]:
            self.active_lists += 1
            return [{
                "id": "legacy-admin-chunk", "title": "旧知识",
                "content": "旧持久卷知识", "source": "demo://legacy-admin",
            }]

        async def recover_stale_knowledge_jobs(
            self, age_seconds: int | None = None
        ) -> int:
            assert age_seconds is None
            return 0

    class Vector:
        activations = 0

        async def activate_chunks(self, _chunks: object) -> None:
            self.activations += 1

    class Security:
        hashes = 0

        def hash_password(self, value: str) -> str:
            self.hashes += 1
            return f"hash:{value}"

    runtime = object.__new__(BusinessRuntime)
    runtime._startup_lock = asyncio.Lock()  # noqa: SLF001
    runtime._startup_complete = False  # noqa: SLF001
    runtime._vision_cleanup_task = None  # noqa: SLF001
    runtime._seed_password_hashes = None  # noqa: SLF001
    runtime.object_store = Store()
    runtime.repository = Repository()
    runtime.vector_index = Vector()
    runtime.security = Security()
    runtime.settings = SimpleNamespace(
        vision_enabled=False,
        demo_admin_username="admin.demo",
        demo_admin_password=SimpleNamespace(get_secret_value=lambda: "admin-pass"),
        demo_staff_username="staff.demo",
        demo_staff_password=SimpleNamespace(get_secret_value=lambda: "staff-pass"),
    )

    await asyncio.gather(runtime.startup(), runtime.startup(), runtime.startup())

    assert runtime.object_store.ensures == 1
    assert runtime.repository.seeds == 1
    assert runtime.repository.active_lists == 1
    assert runtime.vector_index.activations == 1
    assert runtime.security.hashes == 2
