from __future__ import annotations

import csv
import io
import math
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.application.dtos import NavigationCatalogRowData, Principal
from app.application.ports import BusinessRepositoryPort
from app.domain.enums import Role
from app.errors import BusinessValidationError, PermissionDenied


class NavigationCatalogCoordinator:
    """Validate and publish a location-free government navigation catalog."""

    max_csv_bytes = 1024 * 1024
    max_csv_rows = 1000
    _max_errors = 100

    _columns = (
        "service_code",
        "window_code",
        "name",
        "address",
        "city_code",
        "longitude",
        "latitude",
        "coordinate_type",
        "opening_hours",
        "priority",
        "handling_mode",
        "online_status",
        "data_mode",
        "source_reference",
        "verified_at",
    )
    _header_aliases = {
        "事项编码": "service_code",
        "网点编码": "window_code",
        "名称": "name",
        "地址": "address",
        "城市": "city_code",
        "经度": "longitude",
        "纬度": "latitude",
        "坐标系": "coordinate_type",
        "开放时间": "opening_hours",
        "优先级": "priority",
        "办理模式": "handling_mode",
        "线上状态": "online_status",
        "数据模式": "data_mode",
        "来源": "source_reference",
        "核验时间": "verified_at",
        **{name: name for name in _columns},
    }
    _handling_aliases = {
        "ONLINE_ONLY": "ONLINE_ONLY",
        "仅线上": "ONLINE_ONLY",
        "OFFLINE_ONLY": "OFFLINE_ONLY",
        "仅线下": "OFFLINE_ONLY",
        "BOTH": "BOTH",
        "线上线下": "BOTH",
        "UNKNOWN": "UNKNOWN",
        "未知": "UNKNOWN",
    }
    _online_aliases = {
        "AVAILABLE": "AVAILABLE",
        "可用": "AVAILABLE",
        "TEMP_UNAVAILABLE": "TEMP_UNAVAILABLE",
        "暂不可用": "TEMP_UNAVAILABLE",
        "UNKNOWN": "UNKNOWN",
        "未知": "UNKNOWN",
    }
    _data_aliases = {
        "DEMO": "DEMO",
        "演示": "DEMO",
        "VERIFIED": "VERIFIED",
        "已核验": "VERIFIED",
    }
    _code_pattern = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{1,63}")
    _city_pattern = re.compile(r"[A-Za-z0-9\u3400-\u9fff][A-Za-z0-9\u3400-\u9fff_.-]{1,31}")

    def __init__(self, repository: BusinessRepositoryPort) -> None:
        self.repository = repository

    async def options(self, service_id: UUID) -> dict[str, Any]:
        return await self.repository.get_navigation_options(service_id)

    async def import_csv(
        self, principal: Principal, content: bytes, *, dry_run: bool
    ) -> dict[str, Any]:
        if principal.role is not Role.ADMIN:
            raise PermissionDenied("仅管理员可导入导航目录")
        rows, report = self._parse(content, dry_run=dry_run)
        if report["errors"]:
            if dry_run:
                return report
            raise BusinessValidationError("导航目录CSV校验失败", report)

        result = await self.repository.import_navigation_catalog(
            principal.account_id, rows, dry_run
        )
        if result.get("errors") and not dry_run:
            raise BusinessValidationError("导航目录CSV校验失败", result)
        return result

    @classmethod
    def _parse(
        cls, content: bytes, *, dry_run: bool
    ) -> tuple[tuple[NavigationCatalogRowData, ...], dict[str, Any]]:
        if not content or len(content) > cls.max_csv_bytes:
            raise BusinessValidationError("导航目录CSV必须非空且不超过1 MiB")
        try:
            text = content.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise BusinessValidationError("导航目录CSV必须使用UTF-8编码") from exc
        if "\x00" in text:
            raise BusinessValidationError("导航目录CSV包含非法空字符")

        try:
            records = list(csv.reader(io.StringIO(text, newline=""), strict=True))
        except csv.Error as exc:
            raise BusinessValidationError("导航目录CSV结构无效") from exc
        if not records:
            raise BusinessValidationError("导航目录CSV缺少表头")
        raw_headers = [value.strip() for value in records[0]]
        canonical_headers = [cls._header_aliases.get(value, "") for value in raw_headers]
        header_errors: list[dict[str, Any]] = []
        if len(raw_headers) != len(cls._columns) or any(not value for value in canonical_headers):
            header_errors.append(
                {
                    "line": 1,
                    "field": "header",
                    "message": "表头必须使用固定的15列中文名称或英文别名",
                }
            )
        elif len(set(canonical_headers)) != len(cls._columns) or set(canonical_headers) != set(cls._columns):
            header_errors.append(
                {
                    "line": 1,
                    "field": "header",
                    "message": "表头存在重复列或缺少必需列",
                }
            )
        data_records = [row for row in records[1:] if any(cell.strip() for cell in row)]
        if len(data_records) > cls.max_csv_rows:
            raise BusinessValidationError("导航目录CSV最多包含1000行数据")
        errors = list(header_errors)
        parsed: list[NavigationCatalogRowData] = []
        seen_links: dict[tuple[str, str], int] = {}
        service_modes: dict[str, tuple[str, str, int]] = {}
        window_values: dict[str, tuple[object, ...]] = {}

        if not errors:
            indexes = {name: canonical_headers.index(name) for name in cls._columns}
            for line_number, cells in enumerate(records[1:], start=2):
                if not any(cell.strip() for cell in cells):
                    continue
                if len(cells) != len(raw_headers):
                    cls._error(errors, line_number, "row", "列数与表头不一致")
                    continue
                values = {
                    name: cells[indexes[name]].strip() for name in cls._columns
                }
                row = cls._parse_row(values, line_number, errors)
                if row is None:
                    continue
                link_key = (row.service_code, row.window_code)
                if link_key in seen_links:
                    cls._error(
                        errors,
                        line_number,
                        "window_code",
                        f"事项与网点关联重复，首次出现在第{seen_links[link_key]}行",
                    )
                    continue
                seen_links[link_key] = line_number

                service_mode = service_modes.get(row.service_code)
                current_mode = (row.handling_mode, row.online_status, line_number)
                if service_mode and service_mode[:2] != current_mode[:2]:
                    cls._error(
                        errors,
                        line_number,
                        "handling_mode",
                        f"同一事项的办理模式和线上状态必须一致，首次出现在第{service_mode[2]}行",
                    )
                    continue
                service_modes[row.service_code] = current_mode

                current_window = (
                    row.name,
                    row.address,
                    row.city_code,
                    row.longitude,
                    row.latitude,
                    row.coordinate_type,
                    row.opening_hours,
                    row.data_mode,
                    row.source_reference,
                    row.verified_at,
                )
                prior_window = window_values.get(row.window_code)
                if prior_window and prior_window[:-1] != current_window:
                    cls._error(
                        errors,
                        line_number,
                        "window_code",
                        "同一网点编码的目录信息不一致",
                    )
                    continue
                window_values[row.window_code] = (*current_window, line_number)
                parsed.append(row)

        if not data_records:
            cls._error(errors, 2, "row", "CSV至少需要一行数据")
        report = {
            "valid": not errors,
            "dry_run": dry_run,
            "rows": len(data_records),
            "services": len({row.service_code for row in parsed}),
            "windows": len({row.window_code for row in parsed}),
            "links": len(parsed),
            "written": False,
            "errors": errors[: cls._max_errors],
        }
        return tuple(parsed), report

    @classmethod
    def _parse_row(
        cls,
        values: dict[str, str],
        line_number: int,
        errors: list[dict[str, Any]],
    ) -> NavigationCatalogRowData | None:
        required = (
            "service_code",
            "window_code",
            "name",
            "address",
            "city_code",
            "longitude",
            "latitude",
            "coordinate_type",
            "opening_hours",
            "priority",
            "handling_mode",
            "online_status",
            "data_mode",
        )
        for field in required:
            if not values[field]:
                cls._error(errors, line_number, field, "不能为空")
        if any(not values[field] for field in required):
            return None
        if not cls._code_pattern.fullmatch(values["service_code"]):
            cls._error(errors, line_number, "service_code", "事项编码格式无效")
        if not cls._code_pattern.fullmatch(values["window_code"]):
            cls._error(errors, line_number, "window_code", "网点编码格式无效")
        if not cls._city_pattern.fullmatch(values["city_code"]):
            cls._error(errors, line_number, "city_code", "城市编码格式无效")
        if not 1 <= len(values["name"]) <= 120:
            cls._error(errors, line_number, "name", "名称长度必须为1至120字符")
        if not 3 <= len(values["address"]) <= 255:
            cls._error(errors, line_number, "address", "地址长度必须为3至255字符")
        if not 1 <= len(values["opening_hours"]) <= 120:
            cls._error(errors, line_number, "opening_hours", "开放时间长度无效")

        longitude = cls._float(values["longitude"], line_number, "longitude", errors)
        latitude = cls._float(values["latitude"], line_number, "latitude", errors)
        if longitude is not None and not 73.0 <= longitude <= 135.0:
            cls._error(errors, line_number, "longitude", "GCJ02经度必须位于中国境内范围")
        if latitude is not None and not 3.0 <= latitude <= 54.0:
            cls._error(errors, line_number, "latitude", "GCJ02纬度必须位于中国境内范围")
        if values["coordinate_type"].upper() != "GCJ02":
            cls._error(errors, line_number, "coordinate_type", "坐标系仅允许GCJ02")
        try:
            priority = int(values["priority"])
            if not 0 <= priority <= 1000:
                raise ValueError
        except ValueError:
            cls._error(errors, line_number, "priority", "优先级必须为0至1000整数")
            priority = -1

        handling_mode = cls._handling_aliases.get(values["handling_mode"].upper())
        if handling_mode is None:
            handling_mode = cls._handling_aliases.get(values["handling_mode"])
        online_status = cls._online_aliases.get(values["online_status"].upper())
        if online_status is None:
            online_status = cls._online_aliases.get(values["online_status"])
        data_mode = cls._data_aliases.get(values["data_mode"].upper())
        if data_mode is None:
            data_mode = cls._data_aliases.get(values["data_mode"])
        if handling_mode is None:
            cls._error(errors, line_number, "handling_mode", "办理模式枚举无效")
        if online_status is None:
            cls._error(errors, line_number, "online_status", "线上状态枚举无效")
        if data_mode is None:
            cls._error(errors, line_number, "data_mode", "数据模式枚举无效")

        source_reference = values["source_reference"] or None
        if source_reference is not None and len(source_reference) > 255:
            cls._error(errors, line_number, "source_reference", "来源长度不能超过255字符")
        verified_at = cls._timestamp(values["verified_at"], line_number, errors)
        if data_mode == "VERIFIED" and (not source_reference or verified_at is None):
            cls._error(
                errors,
                line_number,
                "data_mode",
                "VERIFIED数据必须同时填写来源和带时区的核验时间",
            )
        if errors and any(error["line"] == line_number for error in errors):
            return None
        assert longitude is not None and latitude is not None
        assert handling_mode is not None and online_status is not None and data_mode is not None
        return NavigationCatalogRowData(
            line_number=line_number,
            service_code=values["service_code"].upper(),
            window_code=values["window_code"].upper(),
            name=values["name"],
            address=values["address"],
            city_code=values["city_code"],
            longitude=longitude,
            latitude=latitude,
            coordinate_type="GCJ02",
            opening_hours=values["opening_hours"],
            priority=priority,
            handling_mode=handling_mode,  # type: ignore[arg-type]
            online_status=online_status,  # type: ignore[arg-type]
            data_mode=data_mode,  # type: ignore[arg-type]
            source_reference=source_reference,
            verified_at=verified_at,
        )

    @staticmethod
    def _float(
        raw: str,
        line_number: int,
        field: str,
        errors: list[dict[str, Any]],
    ) -> float | None:
        try:
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError
            return value
        except ValueError:
            NavigationCatalogCoordinator._error(
                errors, line_number, field, "必须是有限数字"
            )
            return None

    @staticmethod
    def _timestamp(
        raw: str, line_number: int, errors: list[dict[str, Any]]
    ) -> datetime | None:
        if not raw:
            return None
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if value.tzinfo is None:
                raise ValueError
            return value.astimezone(timezone.utc)
        except ValueError:
            NavigationCatalogCoordinator._error(
                errors, line_number, "verified_at", "核验时间必须是带时区的ISO-8601时间"
            )
            return None

    @staticmethod
    def _error(
        errors: list[dict[str, Any]], line: int, field: str, message: str
    ) -> None:
        if len(errors) < NavigationCatalogCoordinator._max_errors:
            errors.append({"line": line, "field": field, "message": message})
