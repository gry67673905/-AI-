from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.application.dtos import NavigationCatalogRowData, Principal
from app.application.navigation import NavigationCatalogCoordinator
from app.boundaries.http import AdminConsoleBoundary, CitizenPortalBoundary
from app.domain.enums import Role
from app.errors import BusinessValidationError, PermissionDenied, ResourceNotFound
from app.infrastructure.records import (
    GovernmentServiceRecord,
    ServiceWindowLinkRecord,
    ServiceWindowRecord,
)
from app.infrastructure.repositories import BusinessRepository


HEADER_ZH = (
    "事项编码,网点编码,名称,地址,城市,经度,纬度,坐标系,开放时间,优先级,"
    "办理模式,线上状态,数据模式,来源,核验时间\n"
)
HEADER_EN = (
    "service_code,window_code,name,address,city_code,longitude,latitude,"
    "coordinate_type,opening_hours,priority,handling_mode,online_status,"
    "data_mode,source_reference,verified_at\n"
)


def _principal(role: Role = Role.ADMIN) -> Principal:
    return Principal(
        account_id=uuid4(),
        username=role.value.lower(),
        display_name=role.value,
        role=role,
        applicant_type=None,
        token_version=0,
    )


class _Repository:
    def __init__(self) -> None:
        self.import_calls: list[tuple[object, tuple[object, ...], bool]] = []
        self.options_calls: list[object] = []

    async def get_navigation_options(self, service_id):
        self.options_calls.append(service_id)
        return {
            "service": {
                "id": service_id,
                "code": "DEMO-ID-REISSUE-001",
                "name": "居民身份证补领",
                "handling_mode": "OFFLINE_ONLY",
                "online_status": "UNKNOWN",
                "status_reason": "需线下核验",
                "status_updated_at": None,
            },
            "windows": [],
            "active_location_count": 0,
            "demo_only": False,
            "notice": "当前没有已启用的线下网点。",
        }

    async def import_navigation_catalog(self, actor_id, rows, dry_run):
        self.import_calls.append((actor_id, rows, dry_run))
        return {
            "valid": True,
            "dry_run": dry_run,
            "rows": len(rows),
            "services": len({row.service_code for row in rows}),
            "windows": len({row.window_code for row in rows}),
            "links": len(rows),
            "written": not dry_run,
            "errors": [],
        }


class _Result:
    def __init__(self, values):
        self.values = values

    def first(self):
        return self.values

    def all(self):
        return list(self.values)


class _ReadSession:
    def __init__(self, results: list[_Result]) -> None:
        self.results = list(results)
        self.statements: list[object] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)


class _ReadSessions:
    def __init__(self, session: _ReadSession) -> None:
        self.session = session

    def __call__(self):
        return self.session


class _ScalarResult:
    def __init__(self, values) -> None:
        self.values = values

    def all(self):
        return list(self.values)


class _Transaction:
    def __init__(self, session: "_ImportSession") -> None:
        self.session = session

    async def __aenter__(self):
        assert not self.session.in_transaction
        self.session.in_transaction = True
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        self.session.in_transaction = False
        self.session.committed = exc_type is None
        self.session.rolled_back = exc_type is not None
        return False


class _ImportSession:
    def __init__(
        self, services, windows, *, existing_links=(), fail_flush: bool = False
    ) -> None:
        self.scalar_results = [
            _ScalarResult(services),
            _ScalarResult(windows),
            _ScalarResult(existing_links),
        ]
        self.links: dict[tuple[object, object], object] = {
            (item.service_id, item.window_id): item for item in existing_links
        }
        self.added: list[object] = []
        self.fail_flush = fail_flush
        self.in_transaction = False
        self.committed = False
        self.rolled_back = False
        self.flush_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def begin(self):
        return _Transaction(self)

    async def scalars(self, statement):
        assert self.in_transaction
        return self.scalar_results.pop(0)

    async def get(self, model, key):
        assert self.in_transaction
        assert model is ServiceWindowLinkRecord
        return self.links.get(key)

    def add(self, value):
        assert self.in_transaction
        self.added.append(value)
        if isinstance(value, ServiceWindowLinkRecord):
            self.links[(value.service_id, value.window_id)] = value

    async def flush(self):
        assert self.in_transaction
        self.flush_count += 1
        if self.fail_flush:
            raise RuntimeError("simulated write failure")


class _ImportSessions:
    def __init__(self, session: _ImportSession) -> None:
        self.session = session

    def __call__(self):
        return self.session


def _catalog_row(
    *,
    line: int = 2,
    service_code: str = "DEMO-ID-REISSUE-001",
    window_code: str = "POLICE-HUKOU-01",
    priority: int = 0,
) -> NavigationCatalogRowData:
    return NavigationCatalogRowData(
        line_number=line,
        service_code=service_code,
        window_code=window_code,
        name="演示公安大厅",
        address="演示市政务路100号",
        city_code="DEMO-CITY",
        longitude=116.397128,
        latitude=39.916527,
        coordinate_type="GCJ02",
        opening_hours="工作日09:00-17:00",
        priority=priority,
        handling_mode="OFFLINE_ONLY",
        online_status="UNKNOWN",
        data_mode="DEMO",
        source_reference="demo://navigation",
        verified_at=None,
    )


def _service_and_version(*, published: bool = True):
    service_id = uuid4()
    version_id = uuid4()
    department_id = uuid4()
    service = SimpleNamespace(
        id=service_id,
        code="DEMO-ID-REISSUE-001",
        department_id=department_id,
        status="PUBLISHED" if published else "DRAFT",
        current_version_id=version_id,
        handling_mode="OFFLINE_ONLY",
        online_status="UNKNOWN",
        status_reason="需线下办理",
        status_updated_at=None,
        window_id=None,
    )
    version = SimpleNamespace(id=version_id, title="居民身份证补领")
    return service, version


def _window(code: str, *, active: bool = True, data_mode: str = "DEMO"):
    return SimpleNamespace(
        id=uuid4(),
        code=code,
        name=f"{code}大厅",
        address="演示市政务路100号",
        opening_hours="工作日09:00-17:00",
        latitude=39.916527,
        longitude=116.397128,
        coordinate_type="GCJ02",
        data_mode=data_mode,
        city_code="DEMO-CITY",
        source_reference="demo://navigation" if data_mode == "DEMO" else "gov://catalog",
        verified_at=(
            None
            if data_mode == "DEMO"
            else datetime(2026, 8, 25, tzinfo=timezone.utc)
        ),
        active=active,
    )


@pytest.mark.asyncio
async def test_navigation_options_are_location_free_and_anonymous() -> None:
    repository = _Repository()
    coordinator = NavigationCatalogCoordinator(repository)  # type: ignore[arg-type]
    service_id = uuid4()

    result = await coordinator.options(service_id)

    assert repository.options_calls == [service_id]
    assert set(result) == {
        "service",
        "windows",
        "active_location_count",
        "demo_only",
        "notice",
    }
    assert "user_location" not in repr(result)
    public_paths = {route.path for route in CitizenPortalBoundary().router.routes}
    assert "/services/{service_id}/navigation-options" in public_paths


@pytest.mark.asyncio
async def test_utf8_bom_chinese_csv_dry_run_parses_without_writing() -> None:
    repository = _Repository()
    coordinator = NavigationCatalogCoordinator(repository)  # type: ignore[arg-type]
    content = (
        "\ufeff"
        + HEADER_ZH
        + "DEMO-ID-REISSUE-001,POLICE-NAV-01,演示公安大厅,演示市政务路100号,"
        "DEMO-CITY,116.397128,39.916527,GCJ02,工作日09:00-17:00,0,"
        "OFFLINE_ONLY,UNKNOWN,DEMO,demo://navigation,\n"
    ).encode("utf-8")

    result = await coordinator.import_csv(_principal(), content, dry_run=True)

    assert result["valid"] is True
    assert result["written"] is False
    assert result["rows"] == 1
    assert len(repository.import_calls) == 1
    _, rows, dry_run = repository.import_calls[0]
    assert dry_run is True
    assert rows[0].service_code == "DEMO-ID-REISSUE-001"
    assert rows[0].longitude == pytest.approx(116.397128)
    assert rows[0].handling_mode == "OFFLINE_ONLY"


@pytest.mark.asyncio
async def test_english_alias_csv_can_be_atomically_imported() -> None:
    repository = _Repository()
    coordinator = NavigationCatalogCoordinator(repository)  # type: ignore[arg-type]
    content = (
        HEADER_EN
        + "DEMO-SS-CARD-001,HRSS-NAV-01,Social service demo,Demo Road 88,"
        "DEMO-CITY,116.407526,39.904030,GCJ02,Weekdays 08:30-17:30,10,"
        "BOTH,AVAILABLE,VERIFIED,gov://catalog/42,2026-08-25T09:30:00+08:00\n"
    ).encode()

    result = await coordinator.import_csv(_principal(), content, dry_run=False)

    assert result["written"] is True
    _, rows, dry_run = repository.import_calls[0]
    assert dry_run is False
    assert rows[0].data_mode == "VERIFIED"
    assert rows[0].verified_at == datetime(
        2026, 8, 25, 1, 30, tzinfo=timezone.utc
    )


@pytest.mark.asyncio
async def test_csv_reports_duplicate_and_invalid_gcj02_with_line_numbers() -> None:
    repository = _Repository()
    coordinator = NavigationCatalogCoordinator(repository)  # type: ignore[arg-type]
    first = (
        "DEMO-ID-REISSUE-001,POLICE-NAV-01,演示公安大厅,演示市政务路100号,"
        "DEMO-CITY,116.39,39.91,GCJ02,工作日,0,OFFLINE_ONLY,UNKNOWN,DEMO,,\n"
    )
    duplicate = first
    invalid = (
        "DEMO-SS-CARD-001,HRSS-NAV-01,演示人社大厅,演示市民生路88号,"
        "DEMO-CITY,200,91,WGS84,工作日,0,BOTH,NOT_A_STATUS,DEMO,,\n"
    )

    result = await coordinator.import_csv(
        _principal(), (HEADER_ZH + first + duplicate + invalid).encode(), dry_run=True
    )

    assert result["valid"] is False
    assert repository.import_calls == []
    errors = {(item["line"], item["field"]) for item in result["errors"]}
    assert (3, "window_code") in errors
    assert (4, "longitude") in errors
    assert (4, "latitude") in errors
    assert (4, "coordinate_type") in errors
    assert (4, "online_status") in errors


@pytest.mark.asyncio
async def test_verified_row_requires_source_and_zoned_verification_time() -> None:
    repository = _Repository()
    coordinator = NavigationCatalogCoordinator(repository)  # type: ignore[arg-type]
    row = (
        "DEMO-ID-REISSUE-001,POLICE-NAV-01,演示公安大厅,演示市政务路100号,"
        "DEMO-CITY,116.39,39.91,GCJ02,工作日,0,OFFLINE_ONLY,UNKNOWN,"
        "VERIFIED,,2026-08-25T09:30:00\n"
    )

    result = await coordinator.import_csv(
        _principal(), (HEADER_ZH + row).encode(), dry_run=True
    )

    assert result["valid"] is False
    assert any(item["field"] == "verified_at" for item in result["errors"])
    assert any(item["field"] == "data_mode" for item in result["errors"])


@pytest.mark.asyncio
async def test_real_import_rejects_validation_errors_and_non_admin() -> None:
    repository = _Repository()
    coordinator = NavigationCatalogCoordinator(repository)  # type: ignore[arg-type]

    with pytest.raises(PermissionDenied):
        await coordinator.import_csv(
            _principal(Role.CITIZEN), HEADER_ZH.encode(), dry_run=True
        )
    with pytest.raises(BusinessValidationError):
        await coordinator.import_csv(_principal(), HEADER_ZH.encode(), dry_run=False)
    assert repository.import_calls == []


def test_navigation_records_and_migration_preserve_many_to_many_backfill() -> None:
    assert {
        "handling_mode",
        "online_status",
        "status_reason",
        "status_updated_at",
    } <= set(GovernmentServiceRecord.__table__.c.keys())
    assert {
        "city_code",
        "coordinate_type",
        "data_mode",
        "source_reference",
        "verified_at",
    } <= set(ServiceWindowRecord.__table__.c.keys())
    primary_key = {column.name for column in ServiceWindowLinkRecord.__table__.primary_key}
    assert primary_key == {"service_id", "window_id"}
    service_constraints = {
        constraint.name for constraint in GovernmentServiceRecord.__table__.constraints
    }
    window_constraints = {
        constraint.name for constraint in ServiceWindowRecord.__table__.constraints
    }
    assert {
        "ck_government_services_handling_mode",
        "ck_government_services_online_status",
    } <= service_constraints
    assert {
        "ck_service_windows_coordinate_type",
        "ck_service_windows_data_mode",
    } <= window_constraints

    migration = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "0007_navigation_catalog.py"
    ).read_text(encoding="utf-8")
    assert "SELECT id, window_id, 0, TRUE" in migration
    assert "ON CONFLICT (service_id, window_id) DO NOTHING" in migration


def test_admin_catalog_import_route_is_registered() -> None:
    paths = {route.path for route in AdminConsoleBoundary().router.routes}
    assert "/admin/navigation-catalog/import" in paths


@pytest.mark.parametrize(
    ("modes", "demo_only", "notice_fragment"),
    [
        ([], False, "没有已启用"),
        (["DEMO"], True, "演示网点"),
        (["DEMO", "VERIFIED"], True, "包含演示网点"),
        (["VERIFIED", "VERIFIED"], False, "管理员核验目录"),
    ],
)
def test_demo_warning_remains_for_mixed_catalog_rows(
    modes: list[str], demo_only: bool, notice_fragment: str
) -> None:
    windows = [{"data_mode": mode} for mode in modes]

    actual_demo_only, notice = BusinessRepository._navigation_catalog_notice(
        windows
    )

    assert actual_demo_only is demo_only
    assert notice_fragment in notice


def test_checked_in_csv_fixtures_are_utf8_and_use_fixed_headers() -> None:
    fixture_dir = Path(__file__).parents[1] / "fixtures"
    for name in (
        "navigation_catalog_template.csv",
        "navigation_catalog_demo.csv",
        "navigation_catalog_chengdu_device_test.csv",
    ):
        text = (fixture_dir / name).read_bytes().decode("utf-8-sig")
        assert text.splitlines()[0] == HEADER_ZH.strip()


@pytest.mark.asyncio
async def test_chengdu_device_fixture_dry_run_and_import_contract() -> None:
    repository = _Repository()
    coordinator = NavigationCatalogCoordinator(repository)  # type: ignore[arg-type]
    fixture = (
        Path(__file__).parents[1]
        / "fixtures"
        / "navigation_catalog_chengdu_device_test.csv"
    ).read_bytes()

    dry_run = await coordinator.import_csv(
        _principal(), fixture, dry_run=True
    )

    assert dry_run == {
        "valid": True,
        "dry_run": True,
        "rows": 6,
        "services": 2,
        "windows": 6,
        "links": 6,
        "written": False,
        "errors": [],
    }
    _, parsed_rows, _ = repository.import_calls[-1]
    assert {row.city_code for row in parsed_rows} == {"510100"}
    assert {row.coordinate_type for row in parsed_rows} == {"GCJ02"}
    assert {row.data_mode for row in parsed_rows} == {"DEMO"}
    assert {row.source_reference for row in parsed_rows} == {
        "demo://chengdu-device-test"
    }
    expected_coordinates = {
        (104.0668, 30.6573),
        (104.0815, 30.6505),
        (104.0438, 30.6329),
    }
    for service_code in (
        "DEMO-ID-REISSUE-001",
        "DEMO-HOUSING-FUND-001",
    ):
        service_rows = [
            row for row in parsed_rows if row.service_code == service_code
        ]
        assert len(service_rows) == 3
        assert {row.priority for row in service_rows} == {0, 10, 20}
        assert {
            (row.longitude, row.latitude) for row in service_rows
        } == expected_coordinates

    imported = await coordinator.import_csv(
        _principal(), fixture, dry_run=False
    )
    assert imported["valid"] is True
    assert imported["written"] is True
    assert imported["links"] == 6
    assert repository.import_calls[-1][2] is False


@pytest.mark.asyncio
async def test_repository_returns_multiple_windows_in_priority_order_and_filters_active_rows() -> None:
    service, version = _service_and_version()
    high = _window("WINDOW-HIGH", data_mode="VERIFIED")
    low = _window("WINDOW-LOW", data_mode="DEMO")
    read_session = _ReadSession(
        [
            _Result((service, version)),
            _Result(
                [
                    (SimpleNamespace(priority=0), high),
                    (SimpleNamespace(priority=20), low),
                ]
            ),
        ]
    )
    repository = BusinessRepository(_ReadSessions(read_session))  # type: ignore[arg-type]

    result = await repository.get_navigation_options(service.id)

    assert [item["code"] for item in result["windows"]] == [
        "WINDOW-HIGH",
        "WINDOW-LOW",
    ]
    assert [item["priority"] for item in result["windows"]] == [0, 20]
    assert result["active_location_count"] == 2
    assert result["demo_only"] is True
    assert "演示网点" in result["notice"]
    service_sql, windows_sql = map(str, read_session.statements)
    assert "government_services.status" in service_sql
    assert "service_window_links.active IS true" in windows_sql
    assert "service_windows.active IS true" in windows_sql
    assert "ORDER BY service_window_links.priority, service_windows.code" in windows_sql


@pytest.mark.asyncio
async def test_repository_conceals_unpublished_or_missing_service() -> None:
    read_session = _ReadSession([_Result(None)])
    repository = BusinessRepository(_ReadSessions(read_session))  # type: ignore[arg-type]

    with pytest.raises(ResourceNotFound):
        await repository.get_navigation_options(uuid4())

    assert len(read_session.statements) == 1
    assert "government_services.status" in str(read_session.statements[0])


@pytest.mark.asyncio
async def test_repository_import_upserts_two_links_in_one_transaction() -> None:
    service, _ = _service_and_version()
    first = _window("POLICE-HUKOU-01")
    second = _window("POLICE-NAV-02")
    first.department_id = service.department_id
    second.department_id = service.department_id
    session = _ImportSession([service], [first, second])
    repository = BusinessRepository(_ImportSessions(session))  # type: ignore[arg-type]
    rows = (
        _catalog_row(window_code=first.code, priority=0),
        _catalog_row(line=3, window_code=second.code, priority=10),
    )

    result = await repository.import_navigation_catalog(
        uuid4(), rows, dry_run=False
    )

    assert result == {
        "valid": True,
        "dry_run": False,
        "rows": 2,
        "services": 1,
        "windows": 2,
        "links": 2,
        "written": True,
        "errors": [],
    }
    links = [item for item in session.added if isinstance(item, ServiceWindowLinkRecord)]
    assert len(links) == 2
    assert sorted(item.priority for item in links) == [0, 10]
    assert service.window_id in {first.id, second.id}
    assert session.committed is True
    assert session.rolled_back is False


@pytest.mark.asyncio
async def test_repository_import_is_snapshot_and_removes_old_demo_association() -> None:
    service, version = _service_and_version()
    demo = _window("POLICE-DEMO-01", data_mode="DEMO")
    verified = _window("POLICE-VERIFIED-01", data_mode="VERIFIED")
    demo.department_id = service.department_id
    verified.department_id = service.department_id
    service.window_id = demo.id
    old_link = ServiceWindowLinkRecord(
        service_id=service.id,
        window_id=demo.id,
        priority=0,
        active=True,
    )
    session = _ImportSession(
        [service], [demo, verified], existing_links=[old_link]
    )
    repository = BusinessRepository(_ImportSessions(session))  # type: ignore[arg-type]
    verified_row = replace(
        _catalog_row(window_code=verified.code, priority=5),
        data_mode="VERIFIED",
        source_reference="gov://verified/catalog/1",
        verified_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
    )

    result = await repository.import_navigation_catalog(
        uuid4(), (verified_row,), dry_run=False
    )

    assert result["written"] is True
    assert old_link.active is False
    new_link = session.links[(service.id, verified.id)]
    assert new_link.active is True
    assert new_link.priority == 5
    assert service.window_id == verified.id
    # A window record itself is not globally disabled merely because this
    # service's snapshot stopped referring to it.
    assert demo.active is True

    read_session = _ReadSession(
        [_Result((service, version)), _Result([(new_link, verified)])]
    )
    read_repository = BusinessRepository(  # type: ignore[arg-type]
        _ReadSessions(read_session)
    )
    options = await read_repository.get_navigation_options(service.id)
    assert [item["data_mode"] for item in options["windows"]] == ["VERIFIED"]
    assert options["demo_only"] is False
    assert "管理员核验目录" in options["notice"]


@pytest.mark.asyncio
async def test_repository_snapshot_dry_run_does_not_disable_or_repoint() -> None:
    service, _ = _service_and_version()
    demo = _window("POLICE-DEMO-01", data_mode="DEMO")
    verified = _window("POLICE-VERIFIED-01", data_mode="VERIFIED")
    demo.department_id = service.department_id
    verified.department_id = service.department_id
    service.window_id = demo.id
    old_link = ServiceWindowLinkRecord(
        service_id=service.id,
        window_id=demo.id,
        priority=0,
        active=True,
    )
    session = _ImportSession(
        [service], [demo, verified], existing_links=[old_link]
    )
    repository = BusinessRepository(_ImportSessions(session))  # type: ignore[arg-type]
    verified_row = replace(
        _catalog_row(window_code=verified.code),
        data_mode="VERIFIED",
        source_reference="gov://verified/catalog/1",
        verified_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
    )

    result = await repository.import_navigation_catalog(
        uuid4(), (verified_row,), dry_run=True
    )

    assert result["written"] is False
    assert old_link.active is True
    assert service.window_id == demo.id
    assert (service.id, verified.id) not in session.links
    assert session.added == []


@pytest.mark.asyncio
async def test_repository_import_reports_unknown_service_and_cross_department_window() -> None:
    service, _ = _service_and_version()
    foreign = _window("POLICE-HUKOU-01")
    foreign.department_id = uuid4()
    session = _ImportSession([service], [foreign])
    repository = BusinessRepository(_ImportSessions(session))  # type: ignore[arg-type]
    rows = (
        _catalog_row(window_code=foreign.code),
        _catalog_row(
            line=3,
            service_code="UNKNOWN-SERVICE-001",
            window_code="UNKNOWN-WINDOW-001",
        ),
    )

    result = await repository.import_navigation_catalog(
        uuid4(), rows, dry_run=False
    )

    assert result["written"] is False
    assert result["valid"] is False
    errors = {(item["line"], item["field"], item["message"]) for item in result["errors"]}
    assert (2, "window_code", "网点已属于其他部门") in errors
    assert (3, "service_code", "事项编码不存在") in errors
    assert session.added == []
    assert session.committed is True


@pytest.mark.asyncio
async def test_repository_import_failure_rolls_back_whole_file() -> None:
    service, _ = _service_and_version()
    window = _window("POLICE-HUKOU-01")
    window.department_id = service.department_id
    session = _ImportSession([service], [window], fail_flush=True)
    repository = BusinessRepository(_ImportSessions(session))  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="simulated write failure"):
        await repository.import_navigation_catalog(
            uuid4(), (_catalog_row(),), dry_run=False
        )

    assert session.committed is False
    assert session.rolled_back is True
    assert session.flush_count == 1
