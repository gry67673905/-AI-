from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.application.dtos import Principal
from app.application.material_documents import MaterialDocumentCoordinator
from app.domain.enums import (
    ApplicantType,
    ApplicationStatus,
    ConsultationMaterialIntentStatus,
    MaterialDocumentScope,
    MaterialDocumentStatus,
    MaterialTemplateMode,
    Role,
    ServiceStatus,
)
from app.errors import GoneError, PermissionDenied, ResourceNotFound
from app.infrastructure.object_store import InMemoryObjectStore
from app.infrastructure.records import (
    ApplicationRecord,
    ConsultationMaterialIntentRecord,
    GovernmentServiceRecord,
    MaterialDocumentJobRecord,
    MaterialRequirementRecord,
    MaterialTemplateRecord,
    ServiceVersionRecord,
)
from app.infrastructure.repositories import BusinessRepository
from app.models import ChatSession


def _citizen(account_id: UUID | None = None) -> Principal:
    return Principal(
        account_id=account_id or uuid4(),
        username="consultation-citizen",
        display_name="咨询群众",
        role=Role.CITIZEN,
        applicant_type=ApplicantType.INDIVIDUAL,
        token_version=0,
    )


def test_0009_backfills_application_jobs_before_service_columns_become_required() -> None:
    migration = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "0009_consultation_material_documents.py"
    ).read_text(encoding="utf-8")
    backfill = migration.index("UPDATE material_document_jobs AS jobs")
    require_service = migration.index(
        '"service_id",\n        existing_type=sa.Uuid(),\n        nullable=False'
    )
    assert backfill < require_service
    assert "scope = 'APPLICATION'" in migration
    assert "scope = 'CONSULTATION'" in migration


def test_job_and_intent_records_expose_bounded_dual_context_schema() -> None:
    job_columns = MaterialDocumentJobRecord.__table__.c
    assert {
        "scope",
        "service_id",
        "service_version_id",
        "application_id",
        "consultation_session_id",
        "consultation_intent_id",
    }.issubset(job_columns.keys())
    assert job_columns.application_id.nullable
    assert job_columns.application_version.nullable
    constraint_names = {
        constraint.name for constraint in MaterialDocumentJobRecord.__table__.constraints
    }
    assert "ck_material_document_jobs_scope" in constraint_names
    assert "ck_material_document_jobs_context" in constraint_names
    assert "uq_material_document_jobs_consultation_intent" in constraint_names

    intent_columns = ConsultationMaterialIntentRecord.__table__.c
    assert {
        "owner_account_id",
        "session_id",
        "service_id",
        "service_version_id",
        "material_requirement_id",
        "template_id",
        "status",
        "expires_at",
        "confirmed_at",
    }.issubset(intent_columns.keys())
    assert "request_text" not in intent_columns


@pytest.mark.asyncio
async def test_consultation_options_use_current_published_immutable_version() -> None:
    service_id = uuid4()
    current_version_id = uuid4()
    template_id = uuid4()
    service = SimpleNamespace(
        id=service_id,
        code="DEMO-CONSULT-001",
        status=ServiceStatus.PUBLISHED.value,
        current_version_id=current_version_id,
    )
    version = SimpleNamespace(
        id=current_version_id,
        service_id=service_id,
        title="咨询材料演示事项",
        immutable=True,
    )
    requirement = SimpleNamespace(
        code="statement",
        name="情况说明",
        order_index=0,
    )
    template = SimpleNamespace(
        id=template_id,
        template_key="statement-v1",
        title="情况说明模板",
        active=True,
        mode=MaterialTemplateMode.SOURCE_EDITABLE.value,
        source_object_key="material-templates/v1/statement/v1/digest.docx",
        source_sha256="a" * 64,
        notice="演示模板。",
    )
    statements: list[object] = []

    class Rows:
        @staticmethod
        def all() -> list[tuple[object, object]]:
            return [(requirement, template)]

    class Session:
        async def get(self, model: object, identity: object) -> object | None:
            if model is GovernmentServiceRecord and identity == service_id:
                return service
            if model is ServiceVersionRecord and identity == current_version_id:
                return version
            return None

        async def execute(self, statement: object) -> Rows:
            statements.append(statement)
            return Rows()

    class Context:
        async def __aenter__(self) -> Session:
            return Session()

        async def __aexit__(self, *_args: object) -> None:
            return None

    repository = BusinessRepository(lambda: Context())  # type: ignore[arg-type]
    items = await repository.list_consultation_material_template_options(service_id)
    assert items == [
        {
            "service_id": service_id,
            "service_version_id": current_version_id,
            "service_code": "DEMO-CONSULT-001",
            "service_title": "咨询材料演示事项",
            "requirement_code": "statement",
            "requirement_name": "情况说明",
            "template_available": True,
            "template_id": template_id,
            "template_key": "statement-v1",
            "template_title": "情况说明模板",
            "mode": MaterialTemplateMode.SOURCE_EDITABLE.value,
            "notice": "演示模板。",
            "demo_data": True,
        }
    ]
    assert current_version_id in statements[0].compile().params.values()  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_cross_service_search_returns_multiple_candidates_without_defaulting() -> None:
    first_service_id, second_service_id = uuid4(), uuid4()
    first_version_id, second_version_id = uuid4(), uuid4()
    first_template_id, second_template_id = uuid4(), uuid4()
    rows = [
        (
            SimpleNamespace(id=first_service_id, code="DEMO-ID-001"),
            SimpleNamespace(
                id=first_version_id, title="身份证补领", immutable=True
            ),
            SimpleNamespace(code="statement", name="遗失情况说明", order_index=0),
            SimpleNamespace(
                id=first_template_id,
                template_key="id-loss-statement-v1",
                title="身份证遗失情况说明模板",
                mode=MaterialTemplateMode.SOURCE_EDITABLE.value,
                notice="演示模板一。",
            ),
        ),
        (
            SimpleNamespace(id=second_service_id, code="DEMO-CARD-002"),
            SimpleNamespace(
                id=second_version_id, title="社保卡补领", immutable=True
            ),
            SimpleNamespace(code="statement", name="遗失情况说明", order_index=0),
            SimpleNamespace(
                id=second_template_id,
                template_key="card-loss-statement-v1",
                title="社保卡遗失情况说明模板",
                mode=MaterialTemplateMode.VISUAL_RECONSTRUCT.value,
                notice="演示模板二。",
            ),
        ),
    ]
    statements: list[object] = []

    class Rows:
        @staticmethod
        def all() -> list[tuple[object, object, object, object]]:
            return rows

    class Session:
        async def execute(self, statement: object) -> Rows:
            statements.append(statement)
            return Rows()

    class Context:
        async def __aenter__(self) -> Session:
            return Session()

        async def __aexit__(self, *_args: object) -> None:
            return None

    repository = BusinessRepository(lambda: Context())  # type: ignore[arg-type]
    items = await repository.list_consultation_material_template_options(
        None, "遗失情况说明"
    )
    assert [item["template_id"] for item in items] == [
        first_template_id,
        second_template_id,
    ]
    assert {item["service_id"] for item in items} == {
        first_service_id,
        second_service_id,
    }
    # Discovery returns candidates only; the caller must not select or create
    # an intent when more than one row matches.
    assert all("intent_id" not in item for item in items)
    sql = str(statements[0])
    assert "government_services.status" in sql
    assert "service_versions.immutable" in sql
    assert "material_templates.active" in sql
    assert "material_templates.mode" in sql
    assert "material_requirements.name" in sql
    assert "material_templates.title" in sql


@pytest.mark.asyncio
async def test_coordinator_creates_five_minute_session_bound_intent_and_confirms() -> None:
    principal = _citizen()
    session_id = uuid4()
    service_id = uuid4()
    template_id = uuid4()
    intent_id = uuid4()
    captured_create: tuple[object, ...] | None = None
    captured_confirm: tuple[object, ...] | None = None

    class Repository:
        async def create_consultation_material_intent(
            self, *args: object
        ) -> dict[str, object]:
            nonlocal captured_create
            captured_create = args
            return {"intent_id": intent_id, "status": "PENDING"}

        async def confirm_consultation_material_intent(
            self, *args: object
        ) -> dict[str, object]:
            nonlocal captured_confirm
            captured_confirm = args
            return {"generation_id": uuid4(), "status": "QUEUED"}

    coordinator = MaterialDocumentCoordinator(
        Repository(),  # type: ignore[arg-type]
        InMemoryObjectStore(),
        object(),
        enabled=True,
        retention_hours=24,
        model_name="qwen-test-v1",
        release_lane="release-test",
        user_daily_limit=7,
        user_active_limit=2,
        global_daily_limit=19,
        global_queue_limit=31,
        consultation_intent_ttl_seconds=300,
    )
    before = datetime.now(timezone.utc)
    await coordinator.create_consultation_intent(
        principal,
        session_id,
        service_id,
        "statement",
        template_id,
        "  生成一份空白说明  ",
    )
    after = datetime.now(timezone.utc)
    assert captured_create is not None
    assert captured_create[:6] == (
        principal.account_id,
        session_id,
        service_id,
        "statement",
        template_id,
        "生成一份空白说明",
    )
    intent_expiry = captured_create[6]
    assert isinstance(intent_expiry, datetime)
    assert before + timedelta(seconds=300) <= intent_expiry <= after + timedelta(
        seconds=300
    )

    await coordinator.confirm_consultation_intent(principal, session_id, intent_id)
    assert captured_confirm is not None
    assert captured_confirm[:3] == (principal.account_id, session_id, intent_id)
    assert captured_confirm[-6:] == (
        "qwen-test-v1",
        "release-test",
        7,
        2,
        19,
        31,
    )
    staff = Principal(
        account_id=uuid4(),
        username="staff",
        display_name="工作人员",
        role=Role.STAFF,
        applicant_type=None,
        token_version=0,
    )
    with pytest.raises(PermissionDenied):
        await coordinator.create_consultation_intent(
            staff, session_id, service_id, "statement", template_id
        )


class _RepositorySession:
    def __init__(self, objects: dict[tuple[object, object], object]) -> None:
        self.objects = objects
        self.added: list[object] = []
        self.execute_calls: list[object] = []

    async def get(
        self, model: object, identity: object, **_kwargs: object
    ) -> object | None:
        return self.objects.get((model, identity))

    async def scalar(self, statement: object) -> object:
        sql = str(statement)
        if "consultation_intent_id" in sql and "count(" not in sql.lower():
            return next(
                (
                    item
                    for item in self.added
                    if isinstance(item, MaterialDocumentJobRecord)
                ),
                None,
            )
        if "material_requirements" in sql and "count(" not in sql.lower():
            return next(
                (
                    value
                    for (model, _identity), value in self.objects.items()
                    if model is MaterialRequirementRecord
                ),
                None,
            )
        return 0

    async def execute(
        self, statement: object, _parameters: object | None = None
    ) -> SimpleNamespace:
        self.execute_calls.append(statement)
        return SimpleNamespace(rowcount=1)

    def add(self, record: object) -> None:
        if getattr(record, "id", None) is None:
            setattr(record, "id", uuid4())
        self.added.append(record)

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_confirm_intent_atomically_creates_one_blank_consultation_job() -> None:
    owner_id = uuid4()
    session_id = uuid4()
    service_id = uuid4()
    version_id = uuid4()
    requirement_id = uuid4()
    template_id = uuid4()
    intent_id = uuid4()
    now = datetime.now(timezone.utc)
    chat = SimpleNamespace(id=session_id, owner_account_id=owner_id)
    service = SimpleNamespace(
        id=service_id,
        status=ServiceStatus.PUBLISHED.value,
        current_version_id=version_id,
    )
    version = SimpleNamespace(
        id=version_id,
        service_id=service_id,
        title="咨询事项",
        immutable=True,
    )
    requirement = SimpleNamespace(
        id=requirement_id,
        service_version_id=version_id,
        code="statement",
        name="情况说明",
    )
    template = SimpleNamespace(
        id=template_id,
        material_requirement_id=requirement_id,
        template_key="statement-v1",
        version=1,
        title="情况说明模板",
        mode=MaterialTemplateMode.SOURCE_EDITABLE.value,
        allowed_fields=["applicant_name"],
        source_object_key="material-templates/v1/statement/v1/digest.docx",
        source_sha256="a" * 64,
        notice="演示模板。",
        active=True,
    )
    intent = SimpleNamespace(
        id=intent_id,
        owner_account_id=owner_id,
        session_id=session_id,
        service_id=service_id,
        service_version_id=version_id,
        material_requirement_id=requirement_id,
        template_id=template_id,
        requirement_code="statement",
        status=ConsultationMaterialIntentStatus.PENDING.value,
        expires_at=now + timedelta(minutes=5),
        confirmed_at=None,
    )
    session = _RepositorySession(
        {
            (ConsultationMaterialIntentRecord, intent_id): intent,
            (ChatSession, session_id): chat,
            (GovernmentServiceRecord, service_id): service,
            (ServiceVersionRecord, version_id): version,
            (MaterialRequirementRecord, requirement_id): requirement,
            (MaterialTemplateRecord, template_id): template,
        }
    )
    repository = BusinessRepository(object())  # type: ignore[arg-type]
    token = repository._uow_session.set(session)  # type: ignore[arg-type]
    try:
        result = await repository.confirm_consultation_material_intent(
            owner_id,
            session_id,
            intent_id,
            now + timedelta(hours=24),
            "qwen-test-v1",
            "release-test",
            10,
            2,
            20,
            50,
        )
        jobs = [
            item
            for item in session.added
            if isinstance(item, MaterialDocumentJobRecord)
        ]
        assert len(jobs) == 1
        job = jobs[0]
        assert result["generation_id"] == job.id
        assert result["scope"] == MaterialDocumentScope.CONSULTATION.value
        assert result["application_id"] is None
        assert result["consultation_session_id"] == session_id
        assert job.form_snapshot == {}
        assert job.request_text is None
        assert job.service_id == service_id
        assert job.service_version_id == version_id
        assert intent.status == ConsultationMaterialIntentStatus.CONFIRMED.value

        replay = await repository.confirm_consultation_material_intent(
            owner_id,
            session_id,
            intent_id,
            now + timedelta(hours=24),
            "qwen-test-v1",
            "release-test",
            10,
            2,
            20,
            50,
        )
        assert replay["generation_id"] == job.id
        assert len(
            [
                item
                for item in session.added
                if isinstance(item, MaterialDocumentJobRecord)
            ]
        ) == 1
    finally:
        repository._uow_session.reset(token)


@pytest.mark.asyncio
async def test_confirm_rejects_cross_session_and_expired_intent_without_job() -> None:
    owner_id = uuid4()
    session_id = uuid4()
    intent_id = uuid4()
    intent = SimpleNamespace(
        id=intent_id,
        owner_account_id=owner_id,
        session_id=session_id,
        material_requirement_id=uuid4(),
        template_id=uuid4(),
        service_version_id=uuid4(),
        status=ConsultationMaterialIntentStatus.PENDING.value,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    requirement = SimpleNamespace()
    template = SimpleNamespace()
    version = SimpleNamespace()
    session = _RepositorySession(
        {
            (ConsultationMaterialIntentRecord, intent_id): intent,
            (MaterialRequirementRecord, intent.material_requirement_id): requirement,
            (MaterialTemplateRecord, intent.template_id): template,
            (ServiceVersionRecord, intent.service_version_id): version,
        }
    )
    repository = BusinessRepository(object())  # type: ignore[arg-type]
    token = repository._uow_session.set(session)  # type: ignore[arg-type]
    try:
        with pytest.raises(ResourceNotFound):
            await repository.confirm_consultation_material_intent(
                owner_id,
                uuid4(),
                intent_id,
                datetime.now(timezone.utc) + timedelta(hours=24),
                "qwen-test-v1",
                "release-test",
                10,
                2,
                20,
                50,
            )
        with pytest.raises(GoneError):
            await repository.confirm_consultation_material_intent(
                owner_id,
                session_id,
                intent_id,
                datetime.now(timezone.utc) + timedelta(hours=24),
                "qwen-test-v1",
                "release-test",
                10,
                2,
                20,
                50,
            )
        assert not any(
            isinstance(item, MaterialDocumentJobRecord) for item in session.added
        )
    finally:
        repository._uow_session.reset(token)


@pytest.mark.asyncio
async def test_existing_application_job_populates_application_scope_snapshots() -> None:
    owner_id = uuid4()
    application_id = uuid4()
    service_id = uuid4()
    version_id = uuid4()
    requirement_id = uuid4()
    template_id = uuid4()
    app = SimpleNamespace(
        id=application_id,
        applicant_id=owner_id,
        service_id=service_id,
        service_version_id=version_id,
        status=ApplicationStatus.DRAFT.value,
        form_data={"applicant_name": "演示用户"},
        version=3,
    )
    service = SimpleNamespace(
        id=service_id,
        status=ServiceStatus.PUBLISHED.value,
    )
    requirement = SimpleNamespace(
        id=requirement_id,
        service_version_id=version_id,
        code="statement",
    )
    template = SimpleNamespace(
        id=template_id,
        material_requirement_id=requirement_id,
        template_key="statement-v1",
        version=1,
        title="情况说明模板",
        mode=MaterialTemplateMode.SOURCE_EDITABLE.value,
        allowed_fields=["applicant_name"],
        source_object_key="material-templates/v1/statement/v1/digest.docx",
        source_sha256="a" * 64,
        active=True,
    )
    session = _RepositorySession(
        {
            (ApplicationRecord, application_id): app,
            (GovernmentServiceRecord, service_id): service,
            (MaterialRequirementRecord, requirement_id): requirement,
            (MaterialTemplateRecord, template_id): template,
        }
    )
    repository = BusinessRepository(object())  # type: ignore[arg-type]
    token = repository._uow_session.set(session)  # type: ignore[arg-type]
    try:
        result = await repository.create_material_document_job(
            owner_id,
            application_id,
            "statement",
            template_id,
            None,
            datetime.now(timezone.utc) + timedelta(hours=24),
            "qwen-test-v1",
            "release-test",
            10,
            2,
            20,
            50,
        )
    finally:
        repository._uow_session.reset(token)
    job = next(
        item for item in session.added if isinstance(item, MaterialDocumentJobRecord)
    )
    assert result["scope"] == MaterialDocumentScope.APPLICATION.value
    assert result["application_id"] == application_id
    assert result["consultation_session_id"] is None
    assert job.service_id == service_id
    assert job.service_version_id == version_id
    assert job.form_snapshot == {"applicant_name": "演示用户"}


@pytest.mark.asyncio
async def test_consultation_job_is_leased_with_empty_form_and_optional_application() -> None:
    job = SimpleNamespace(
        id=uuid4(),
        owner_account_id=uuid4(),
        scope=MaterialDocumentScope.CONSULTATION.value,
        service_id=uuid4(),
        service_version_id=uuid4(),
        application_id=None,
        consultation_session_id=uuid4(),
        consultation_intent_id=uuid4(),
        requirement_code="statement",
        template_id=uuid4(),
        template_key_snapshot="statement-v1",
        template_title_snapshot="情况说明模板",
        template_mode_snapshot=MaterialTemplateMode.SOURCE_EDITABLE.value,
        allowed_fields_snapshot=[],
        source_object_key_snapshot="material-templates/v1/statement/v1/digest.docx",
        source_sha256_snapshot="a" * 64,
        model_name_snapshot="qwen-test-v1",
        form_snapshot={},
        request_text=None,
        status=MaterialDocumentStatus.QUEUED.value,
        lease_token=None,
        leased_until=None,
    )

    class Scalars:
        @staticmethod
        def all() -> list[object]:
            return []

    class Session:
        async def scalars(self, _statement: object) -> Scalars:
            return Scalars()

        async def scalar(self, _statement: object) -> object:
            return job

    class Context:
        async def __aenter__(self) -> Session:
            return Session()

        async def __aexit__(self, *_args: object) -> None:
            return None

    class Sessions:
        @staticmethod
        def begin() -> Context:
            return Context()

    repository = BusinessRepository(Sessions())  # type: ignore[arg-type]
    leased = await repository.lease_material_document_job(180, "release-test")
    assert leased is not None
    assert leased.scope is MaterialDocumentScope.CONSULTATION
    assert leased.application_id is None
    assert leased.consultation_session_id == job.consultation_session_id
    assert leased.form_snapshot == {}


@pytest.mark.asyncio
async def test_intent_state_hydration_is_owner_session_scoped_and_safe() -> None:
    owner_id = uuid4()
    session_id = uuid4()
    intent_id = uuid4()
    generation_id = uuid4()
    now = datetime.now(timezone.utc)
    intent = SimpleNamespace(
        id=intent_id,
        status=ConsultationMaterialIntentStatus.CONFIRMED.value,
        expires_at=now - timedelta(minutes=1),
    )
    job = SimpleNamespace(
        id=generation_id,
        status=MaterialDocumentStatus.READY.value,
        expires_at=now - timedelta(seconds=1),
        output_object_key="must-not-leak/private.docx",
    )
    statements: list[object] = []

    class Rows:
        @staticmethod
        def all() -> list[tuple[object, object]]:
            return [(intent, job)]

    class Session:
        async def execute(self, statement: object) -> Rows:
            statements.append(statement)
            return Rows()

    class Context:
        async def __aenter__(self) -> Session:
            return Session()

        async def __aexit__(self, *_args: object) -> None:
            return None

    repository = BusinessRepository(lambda: Context())  # type: ignore[arg-type]
    states = await repository.get_consultation_material_intent_states(
        owner_id, session_id, (intent_id,), now
    )
    assert set(states[intent_id]) == {
        "intent_id",
        "intent_status",
        "intent_expires_at",
        "generation_id",
        "generation_status",
        "generation_expires_at",
    }
    assert states[intent_id]["generation_id"] == generation_id
    assert states[intent_id]["generation_status"] == MaterialDocumentStatus.EXPIRED.value
    sql = statements[0].compile()
    assert owner_id in sql.params.values()
    assert session_id in sql.params.values()
    assert "output_object_key" not in states[intent_id]


@pytest.mark.asyncio
async def test_latest_pending_intent_requires_current_active_template_without_enqueue() -> None:
    owner_id = uuid4()
    session_id = uuid4()
    service_id = uuid4()
    version_id = uuid4()
    requirement_id = uuid4()
    template_id = uuid4()
    intent_id = uuid4()
    now = datetime.now(timezone.utc)
    intent = SimpleNamespace(
        id=intent_id,
        owner_account_id=owner_id,
        session_id=session_id,
        service_id=service_id,
        service_version_id=version_id,
        material_requirement_id=requirement_id,
        template_id=template_id,
        requirement_code="statement",
        status=ConsultationMaterialIntentStatus.PENDING.value,
        expires_at=now + timedelta(minutes=5),
        confirmed_at=None,
    )
    service = SimpleNamespace(
        id=service_id,
        status=ServiceStatus.PUBLISHED.value,
        current_version_id=version_id,
    )
    version = SimpleNamespace(
        id=version_id,
        service_id=service_id,
        title="咨询事项",
        immutable=True,
    )
    requirement = SimpleNamespace(
        id=requirement_id,
        service_version_id=version_id,
        code="statement",
        name="情况说明",
    )
    template = SimpleNamespace(
        id=template_id,
        material_requirement_id=requirement_id,
        template_key="statement-v1",
        title="情况说明模板",
        mode=MaterialTemplateMode.SOURCE_EDITABLE.value,
        source_object_key="material-templates/v1/statement/v1/digest.docx",
        source_sha256="a" * 64,
        notice="演示模板。",
        active=True,
    )
    scalar_statements: list[object] = []

    class Scalars:
        @staticmethod
        def all() -> list[object]:
            return [intent]

    class Session:
        async def scalars(self, statement: object) -> Scalars:
            scalar_statements.append(statement)
            return Scalars()

        async def get(self, model: object, identity: object) -> object | None:
            return {
                (GovernmentServiceRecord, service_id): service,
                (ServiceVersionRecord, version_id): version,
                (MaterialRequirementRecord, requirement_id): requirement,
                (MaterialTemplateRecord, template_id): template,
            }.get((model, identity))

    class Context:
        async def __aenter__(self) -> Session:
            return Session()

        async def __aexit__(self, *_args: object) -> None:
            return None

    repository = BusinessRepository(lambda: Context())  # type: ignore[arg-type]
    result = await repository.get_latest_pending_consultation_material_intent(
        owner_id, session_id, now
    )
    assert result is not None
    assert result["intent_id"] == intent_id
    assert result["requires_confirmation"] is True
    assert result["generation_id"] is None
    params = scalar_statements[0].compile().params
    assert owner_id in params.values()
    assert session_id in params.values()


@pytest.mark.parametrize("candidate_count", [0, 2])
@pytest.mark.asyncio
async def test_latest_pending_intent_requires_exactly_one_candidate(
    candidate_count: int,
) -> None:
    owner_id = uuid4()
    session_id = uuid4()
    now = datetime.now(timezone.utc)
    candidates = [SimpleNamespace(id=uuid4()) for _ in range(candidate_count)]

    class Scalars:
        @staticmethod
        def all() -> list[object]:
            return candidates

    class Session:
        async def scalars(self, statement: object) -> Scalars:
            assert statement.compile().params
            return Scalars()

        async def get(self, *_args: object) -> object:
            raise AssertionError("ambiguous candidates must not be hydrated")

    class Context:
        async def __aenter__(self) -> Session:
            return Session()

        async def __aexit__(self, *_args: object) -> None:
            return None

    repository = BusinessRepository(lambda: Context())  # type: ignore[arg-type]
    assert (
        await repository.get_latest_pending_consultation_material_intent(
            owner_id, session_id, now
        )
        is None
    )
