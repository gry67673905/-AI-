from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping
from uuid import UUID

from app.domain.entities import EligibilityResult, MaterialRequirement
from app.domain.enums import (
    AppointmentStatus,
    ApplicationStatus,
    DeliveryStatus,
    EligibilityOutcome,
    HandoffStatus,
    KnowledgeStatus,
    PaymentStatus,
    Role,
    ServiceStatus,
)


class DomainRuleViolation(ValueError):
    """Raised when a requested domain transition or rule is invalid."""


class JsonRuleEvaluator:
    """Interpreter for the deliberately small, non-executable rule DSL."""

    _comparison_ops = {"eq", "ne", "in", "exists", "lt", "lte", "gt", "gte"}
    _logical_ops = {"all", "any", "not"}
    _ordered_ops = {"lt", "lte", "gt", "gte"}
    _field_path = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")

    def validate(self, rule: Mapping[str, Any] | None) -> None:
        """Statically validate the complete DSL tree before using any facts.

        Runtime evaluation cannot discover malformed operands when the first
        referenced field is absent. Publication therefore validates structure,
        arity and operand types independently of application data.
        """

        if rule is None:
            return
        if not isinstance(rule, Mapping) or len(rule) != 1:
            raise DomainRuleViolation("规则必须且只能包含一个操作符")
        operation, argument = next(iter(rule.items()))
        if not isinstance(operation, str):
            raise DomainRuleViolation("规则操作符必须是字符串")
        if operation in {"all", "any"}:
            if not isinstance(argument, list) or not argument:
                raise DomainRuleViolation(f"{operation} 参数必须是非空规则数组")
            for child in argument:
                if not isinstance(child, Mapping):
                    raise DomainRuleViolation(f"{operation} 子项必须是规则对象")
                self.validate(child)
            return
        if operation == "not":
            if not isinstance(argument, Mapping):
                raise DomainRuleViolation("not 参数必须是单个规则对象")
            self.validate(argument)
            return
        if operation not in self._comparison_ops:
            raise DomainRuleViolation(f"不支持的规则操作符: {operation}")

        if operation == "exists" and isinstance(argument, str):
            argument = [argument]
        expected_arity = {1, 2} if operation == "exists" else {2}
        if not isinstance(argument, list) or len(argument) not in expected_arity:
            raise DomainRuleViolation(f"{operation} 参数数量无效")
        field = argument[0]
        if not isinstance(field, str) or not self._field_path.fullmatch(field):
            raise DomainRuleViolation("规则字段路径格式无效")
        if operation == "exists":
            if len(argument) == 2 and not isinstance(argument[1], bool):
                raise DomainRuleViolation("exists 第二个参数必须是布尔值")
            return

        expected = argument[1]
        if operation == "in":
            if not isinstance(expected, (list, tuple, set)) or not expected:
                raise DomainRuleViolation("in 第二个参数必须是非空集合")
            if any(
                not isinstance(item, (str, int, float, bool, type(None)))
                for item in expected
            ):
                raise DomainRuleViolation("in 集合只能包含 JSON 标量")
            return
        if operation in self._ordered_ops:
            if (
                isinstance(expected, bool)
                or not isinstance(expected, (int, float))
                or not math.isfinite(float(expected))
            ):
                raise DomainRuleViolation(f"{operation} 比较值必须是有限数值")
            return
        if not isinstance(expected, (str, int, float, bool, type(None))):
            raise DomainRuleViolation(f"{operation} 比较值必须是 JSON 标量")

    def evaluate(self, rule: Mapping[str, Any] | None, facts: Mapping[str, Any]) -> bool | None:
        self.validate(rule)
        if rule is None:
            return True
        if len(rule) != 1:
            raise DomainRuleViolation("规则必须且只能包含一个操作符")
        operation, argument = next(iter(rule.items()))
        if operation in self._logical_ops:
            return self._evaluate_logical(operation, argument, facts)
        if operation not in self._comparison_ops:
            raise DomainRuleViolation(f"不支持的规则操作符: {operation}")
        if operation == "exists" and isinstance(argument, str):
            argument = [argument]
        if not isinstance(argument, list) or len(argument) not in {1, 2}:
            raise DomainRuleViolation(f"{operation} 参数格式无效")
        field = argument[0]
        if not isinstance(field, str):
            raise DomainRuleViolation("规则字段名必须是字符串")
        present, actual = self._resolve(facts, field)
        if operation == "exists":
            expected = bool(argument[1]) if len(argument) == 2 else True
            if expected:
                return True if present else None
            return not present
        if not present:
            return None
        expected = argument[1]
        try:
            if operation == "eq":
                return actual == expected
            if operation == "ne":
                return actual != expected
            if operation == "in":
                return actual in expected
            if (
                isinstance(actual, bool)
                or not isinstance(actual, (int, float))
                or not math.isfinite(float(actual))
            ):
                raise DomainRuleViolation(f"{operation} 实际值必须是有限数值")
            if operation == "lt":
                return actual < expected
            if operation == "lte":
                return actual <= expected
            if operation == "gt":
                return actual > expected
            return actual >= expected
        except DomainRuleViolation:
            raise
        except (TypeError, ValueError) as exc:
            raise DomainRuleViolation(f"{operation} 参数类型不兼容") from exc

    def _evaluate_logical(
        self, operation: str, argument: Any, facts: Mapping[str, Any]
    ) -> bool | None:
        if operation == "not":
            if not isinstance(argument, Mapping):
                raise DomainRuleViolation("not 参数必须是规则对象")
            value = self.evaluate(argument, facts)
            return None if value is None else not value
        if not isinstance(argument, list) or not argument:
            raise DomainRuleViolation(f"{operation} 参数必须是非空规则数组")
        values = [self.evaluate(item, facts) for item in argument]
        if operation == "all":
            if False in values:
                return False
            return None if None in values else True
        if True in values:
            return True
        return None if None in values else False

    @staticmethod
    def _resolve(facts: Mapping[str, Any], path: str) -> tuple[bool, Any]:
        current: Any = facts
        for segment in path.split("."):
            if not isinstance(current, Mapping) or segment not in current:
                return False, None
            current = current[segment]
        return True, current


class ApplicationStateMachine:
    _allowed: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
        ApplicationStatus.DRAFT: frozenset(
            {ApplicationStatus.SUBMITTED, ApplicationStatus.DISCARDED}
        ),
        ApplicationStatus.SUBMITTED: frozenset(
            {ApplicationStatus.IN_REVIEW, ApplicationStatus.WITHDRAWN}
        ),
        ApplicationStatus.IN_REVIEW: frozenset(
            {
                ApplicationStatus.NEEDS_SUPPLEMENT,
                ApplicationStatus.REJECTED,
                ApplicationStatus.AWAITING_PAYMENT,
                ApplicationStatus.PROCESSING,
            }
        ),
        ApplicationStatus.NEEDS_SUPPLEMENT: frozenset(
            {ApplicationStatus.SUBMITTED, ApplicationStatus.WITHDRAWN}
        ),
        ApplicationStatus.AWAITING_PAYMENT: frozenset(
            {ApplicationStatus.PROCESSING, ApplicationStatus.WITHDRAWN}
        ),
        ApplicationStatus.PROCESSING: frozenset({ApplicationStatus.COMPLETED}),
        ApplicationStatus.REJECTED: frozenset(),
        ApplicationStatus.COMPLETED: frozenset(),
        ApplicationStatus.WITHDRAWN: frozenset(),
        ApplicationStatus.DISCARDED: frozenset(),
    }

    def require(self, current: ApplicationStatus, target: ApplicationStatus) -> None:
        if target not in self._allowed[current]:
            raise DomainRuleViolation(f"办件状态不能从 {current} 变更为 {target}")


class ServiceLifecyclePolicy:
    _allowed: dict[ServiceStatus, frozenset[ServiceStatus]] = {
        ServiceStatus.DRAFT: frozenset({ServiceStatus.PUBLISHED, ServiceStatus.RETIRED}),
        ServiceStatus.PUBLISHED: frozenset({ServiceStatus.SUSPENDED, ServiceStatus.RETIRED}),
        ServiceStatus.SUSPENDED: frozenset({ServiceStatus.PUBLISHED, ServiceStatus.RETIRED}),
        ServiceStatus.RETIRED: frozenset(),
    }

    def require(self, current: ServiceStatus, target: ServiceStatus) -> None:
        if target not in self._allowed[current]:
            raise DomainRuleViolation(f"事项状态不能从 {current} 变更为 {target}")


class EligibilityEvaluator:
    def __init__(self, evaluator: JsonRuleEvaluator | None = None) -> None:
        self._evaluator = evaluator or JsonRuleEvaluator()

    def evaluate(
        self, rules: list[tuple[Mapping[str, Any], str]], facts: Mapping[str, Any]
    ) -> EligibilityResult:
        missing: list[str] = []
        failed: list[str] = []
        for rule, message in rules:
            result = self._evaluator.evaluate(rule, facts)
            if result is None:
                missing.append(message)
            elif not result:
                failed.append(message)
        if failed:
            outcome = EligibilityOutcome.INELIGIBLE
        elif missing:
            outcome = EligibilityOutcome.NEEDS_INFORMATION
        else:
            outcome = EligibilityOutcome.ELIGIBLE
        return EligibilityResult(
            outcome=outcome.value,
            reasons=tuple(failed),
            missing_fields=tuple(missing),
        )


@dataclass(frozen=True, slots=True)
class MaterialDecision:
    code: str
    name: str
    category: str
    reason: str


class MaterialRuleEngine:
    def __init__(self, evaluator: JsonRuleEvaluator | None = None) -> None:
        self._evaluator = evaluator or JsonRuleEvaluator()

    def classify(
        self, requirements: list[MaterialRequirement], facts: Mapping[str, Any]
    ) -> list[MaterialDecision]:
        decisions: list[MaterialDecision] = []
        for item in requirements:
            if item.condition:
                result = self._evaluator.evaluate(item.condition, facts)
                if result is True:
                    category, reason = "CONDITIONAL_REQUIRED", "已满足条件规则"
                elif result is None:
                    category, reason = "NEEDS_INFORMATION", "缺少判断条件"
                else:
                    category, reason = "NOT_APPLICABLE", "条件规则未触发"
            elif item.required:
                category, reason = "REQUIRED", "事项固定必需材料"
            else:
                category, reason = "OPTIONAL", "可选辅助材料"
            decisions.append(MaterialDecision(item.code, item.name, category, reason))
        return decisions


class FormValidationService:
    """Small JSON Schema subset used by the deterministic demo form engine."""

    _type_map = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "object": dict,
        "array": list,
    }

    @classmethod
    def validate_schema(cls, schema: Mapping[str, Any]) -> None:
        if not isinstance(schema, Mapping):
            raise DomainRuleViolation("表单 Schema 必须是对象")
        schema_type = schema.get("type")
        if schema_type is not None and schema_type != "object":
            raise DomainRuleViolation("表单 Schema 顶层类型必须是 object")
        required = schema.get("required", [])
        if (
            not isinstance(required, list)
            or any(not isinstance(item, str) or not item for item in required)
            or len(required) != len(set(required))
        ):
            raise DomainRuleViolation("表单 required 必须是不重复的字段名数组")
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            raise DomainRuleViolation("表单 properties 必须是字段定义对象")
        for field, definition in properties.items():
            if not isinstance(field, str) or not field:
                raise DomainRuleViolation("表单字段名必须是非空字符串")
            if not isinstance(definition, Mapping):
                raise DomainRuleViolation(f"表单字段 {field} 定义必须是对象")
            field_type = definition.get("type")
            if field_type not in cls._type_map:
                raise DomainRuleViolation(f"表单字段 {field} 类型不受支持")
        missing_definitions = set(required) - set(properties)
        if missing_definitions:
            raise DomainRuleViolation("表单必填字段必须存在对应 properties 定义")

    def validate(self, schema: Mapping[str, Any], data: Mapping[str, Any]) -> dict[str, str]:
        self.validate_schema(schema)
        errors: dict[str, str] = {}
        for field in schema.get("required", []):
            if field not in data or data[field] in (None, ""):
                errors[str(field)] = "必填字段缺失"
        for field, definition in schema.get("properties", {}).items():
            if field not in data or not isinstance(definition, Mapping):
                continue
            expected = self._type_map.get(str(definition.get("type", "")))
            field_type = str(definition.get("type", ""))
            # bool subclasses int in Python, while JSON Schema treats boolean,
            # integer and number as disjoint primitive types.
            boolean_as_number = (
                field_type in {"integer", "number"}
                and isinstance(data[field], bool)
            )
            if expected is not None and (
                boolean_as_number or not isinstance(data[field], expected)
            ):
                errors[str(field)] = f"字段类型应为 {definition['type']}"
        return errors


class ReviewDecisionPolicy:
    def require_staff(self, role: Role, assigned_department: str | None, task_department: str) -> None:
        if role is not Role.STAFF or assigned_department != task_department:
            raise DomainRuleViolation("工作人员只能处理所属部门任务")


class AssignmentPolicy:
    def can_claim(self, role: Role, assigned_department: str | None, task_department: str) -> bool:
        return role is Role.STAFF and assigned_department == task_department


class HandoffAccessPolicy:
    def require_staff_access(
        self,
        actor_id: str,
        staff_department: str | None,
        ticket_department: str | None,
        assignee_id: str | None,
        *,
        claiming: bool,
    ) -> None:
        if staff_department is None:
            raise DomainRuleViolation("工作人员未分配部门")
        if ticket_department is not None and ticket_department != staff_department:
            raise DomainRuleViolation("人工咨询不属于当前部门")
        if assignee_id is not None and assignee_id != actor_id:
            raise DomainRuleViolation("人工咨询已被其他工作人员认领")
        if not claiming and assignee_id != actor_id:
            raise DomainRuleViolation("请先认领人工咨询")


class GroundedAnswerPolicy:
    @staticmethod
    def may_answer(source_count: int) -> bool:
        return source_count > 0


class ServiceMatcher:
    """Deterministic service ranking that surfaces ties instead of guessing."""

    _intents = (
        (("劳动合同", "合同备案"), ("劳动合同",)),
        (("企业社保", "企业社会保险", "单位社保"), ("企业", "社会保险")),
        (("个体户", "个体工商户", "个体注册"), ("个体工商户",)),
        (("公积金",), ("公积金",)),
        (("社保卡", "社会保障卡"), ("社会保障卡",)),
        (("身份证",), ("身份证",)),
        (("社保",), ("社会保障", "社会保险")),
    )

    def match(self, query: str, services: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
        required = next(
            (terms for aliases, terms in self._intents if any(alias in query for alias in aliases)),
            (),
        )
        if not required:
            return services[:3], len(services) > 1

        def score(item: dict[str, Any]) -> int:
            text = " ".join(str(item.get(key, "")) for key in ("title", "summary", "code"))
            return sum(100 for term in required if term in text)

        ranked = sorted(services, key=score, reverse=True)
        if not ranked:
            return [], False
        top = score(ranked[0])
        second = score(ranked[1]) if len(ranked) > 1 else -1000
        ambiguous = len(ranked) > 1 and (top <= 0 or top == second)
        return (ranked[:2] if ambiguous else ranked[:3]), ambiguous


class AuthorizedCaseQueryService:
    @staticmethod
    def may_view(role: Role, actor_id: str, owner_id: str, same_department: bool = False) -> bool:
        return role is Role.ADMIN or (role is Role.CITIZEN and actor_id == owner_id) or (
            role is Role.STAFF and same_department
        )


class PaymentStateMachine:
    _allowed = {
        PaymentStatus.CREATED: {PaymentStatus.PENDING, PaymentStatus.CANCELLED},
        PaymentStatus.PENDING: {
            PaymentStatus.SUCCEEDED,
            PaymentStatus.FAILED,
            PaymentStatus.CANCELLED,
        },
        PaymentStatus.FAILED: {PaymentStatus.PENDING, PaymentStatus.CANCELLED},
        PaymentStatus.SUCCEEDED: set(),
        PaymentStatus.CANCELLED: set(),
    }

    def require(self, current: PaymentStatus, target: PaymentStatus) -> None:
        if target not in self._allowed[current]:
            raise DomainRuleViolation(f"缴费状态不能从 {current} 变更为 {target}")


class KnowledgeStateMachine:
    _allowed = {
        KnowledgeStatus.DRAFT: {KnowledgeStatus.INDEXING},
        KnowledgeStatus.INDEXING: {
            KnowledgeStatus.ACTIVE,
            KnowledgeStatus.INDEX_FAILED,
        },
        KnowledgeStatus.INDEX_FAILED: {KnowledgeStatus.INDEXING},
        KnowledgeStatus.ACTIVE: {
            KnowledgeStatus.SUPERSEDED,
            KnowledgeStatus.ARCHIVED,
        },
        KnowledgeStatus.SUPERSEDED: {KnowledgeStatus.ARCHIVED},
        KnowledgeStatus.ARCHIVED: set(),
    }

    def require(self, current: KnowledgeStatus, target: KnowledgeStatus) -> None:
        if target not in self._allowed[current]:
            raise DomainRuleViolation(
                f"知识状态不能从 {current} 变更为 {target}"
            )


class HandoffStateMachine:
    _allowed = {
        HandoffStatus.QUEUED: {HandoffStatus.CLAIMED, HandoffStatus.CANCELLED},
        HandoffStatus.CLAIMED: {HandoffStatus.IN_PROGRESS, HandoffStatus.CANCELLED},
        HandoffStatus.IN_PROGRESS: {HandoffStatus.RESOLVED, HandoffStatus.CANCELLED},
        HandoffStatus.RESOLVED: set(),
        HandoffStatus.CANCELLED: set(),
    }

    def require(self, current: HandoffStatus, target: HandoffStatus) -> None:
        if target not in self._allowed[current]:
            raise DomainRuleViolation(f"人工转接状态不能从 {current} 变更为 {target}")


class AppointmentStateMachine:
    _allowed = {
        AppointmentStatus.BOOKED: {
            AppointmentStatus.CANCELLED,
            AppointmentStatus.COMPLETED,
            AppointmentStatus.NO_SHOW,
        },
        AppointmentStatus.CANCELLED: set(),
        AppointmentStatus.COMPLETED: set(),
        AppointmentStatus.NO_SHOW: set(),
    }

    def require(self, current: AppointmentStatus, target: AppointmentStatus) -> None:
        if target not in self._allowed[current]:
            raise DomainRuleViolation(f"预约状态不能从 {current} 变更为 {target}")


class DeliveryStateMachine:
    _allowed = {
        DeliveryStatus.CREATED: {DeliveryStatus.ACCEPTED, DeliveryStatus.CANCELLED},
        DeliveryStatus.ACCEPTED: {DeliveryStatus.DISPATCHED, DeliveryStatus.CANCELLED},
        DeliveryStatus.DISPATCHED: {DeliveryStatus.DELIVERED},
        DeliveryStatus.DELIVERED: set(),
        DeliveryStatus.CANCELLED: set(),
    }

    def require(self, current: DeliveryStatus, target: DeliveryStatus) -> None:
        if target not in self._allowed[current]:
            raise DomainRuleViolation(f"邮寄状态不能从 {current} 变更为 {target}")


@dataclass(frozen=True, slots=True)
class DigitalHumanIntentProposal:
    intent_type: str
    label: str
    section: str
    prefill: dict[str, Any]


class DigitalHumanIntentPolicy:
    """Map natural-language requests to a closed set of workbench sections.

    This policy never emits an URL, HTTP method, native class name or mutation
    command.  It only proposes navigation; the existing role-aware workbench
    remains responsible for confirmation and subsequent strongly typed calls.
    """

    _role_routes: dict[Role, tuple[tuple[tuple[str, ...], str, str], ...]] = {
        Role.CITIZEN: (
            (("办件", "申请", "草稿", "提交", "补正", "补齐", "上传材料", "撤回", "进度", "邮寄", "配送", "缴费", "缴付", "支付", "预约", "人脸", "核验"), "applications", "前往我的办件确认操作"),
            (("事项", "材料", "流程", "窗口", "资格"), "services", "前往事项服务"),
            (("转人工", "人工咨询", "反馈", "评分", "咨询"), "consultation", "前往咨询工作台"),
            (("账号", "个人资料", "退出"), "profile", "前往账号页面"),
        ),
        Role.STAFF: (
            (("人工咨询", "人工回复", "咨询工单"), "staff_handoffs", "前往人工咨询工作台"),
            (("待办", "认领", "审核", "补正", "驳回", "批准", "完成"), "staff_tasks", "前往审核待办确认操作"),
            (("账号", "个人资料", "退出"), "profile", "前往账号页面"),
        ),
        Role.ADMIN: (
            (("知识", "RAG", "索引", "重试", "归档", "取代"), "admin_knowledge", "前往知识资料管理"),
            (("审计", "日志"), "admin_audit", "前往审计页面"),
            (("部门", "窗口", "人员", "工作人员", "冻结", "解冻", "账号"), "admin_people", "前往人员与组织管理"),
            (("事项", "版本", "发布", "暂停", "恢复", "终止"), "admin_catalog", "前往事项管理确认操作"),
            (("统计", "指标", "概览"), "admin_overview", "前往运营概览"),
            (("个人资料", "退出"), "profile", "前往账号页面"),
        ),
    }
    _anonymous_routes: tuple[tuple[tuple[str, ...], str, str], ...] = (
        (("登录", "注册", "账号"), "login", "前往登录或注册"),
        (("事项", "材料", "流程", "窗口", "资格"), "services", "前往事项服务"),
        (("咨询",), "consultation", "前往咨询页面"),
    )
    _authenticated_terms = (
        "办件", "申请", "补正", "撤回", "进度", "邮寄", "缴费", "支付",
        "预约", "人脸", "核验", "审核", "认领", "驳回", "批准", "完成", "审计",
        "冻结", "解冻", "发布", "暂停", "恢复", "终止", "知识", "索引", "归档",
    )

    def propose(
        self,
        question: str,
        role: Role | None,
        suggested_actions: list[dict[str, Any]],
    ) -> DigitalHumanIntentProposal | None:
        if role is None and any(
            term.lower() in question.lower() for term in self._authenticated_terms
        ):
            return DigitalHumanIntentProposal(
                intent_type="AUTH_REQUIRED",
                label="登录后继续办理",
                section="login",
                prefill={},
            )
        routes = self._anonymous_routes if role is None else self._role_routes[role]
        for terms, section, label in routes:
            if any(term.lower() in question.lower() for term in terms):
                return DigitalHumanIntentProposal(
                    intent_type=(
                        {
                            "login": "OPEN_LOGIN",
                            "services": "OPEN_SERVICES",
                            "consultation": "OPEN_CONSULTATION",
                        }[section]
                        if role is None
                        else "NAVIGATE"
                    ),
                    label=label,
                    section=section,
                    prefill=self._safe_prefill(section, suggested_actions),
                )

        # A grounded, unambiguous service match is itself a useful typed
        # navigation intent even when the utterance contains no generic word
        # such as “事项”.
        if suggested_actions and role in {None, Role.CITIZEN}:
            first = suggested_actions[0]
            if first.get("type") == "VIEW_SERVICE":
                return DigitalHumanIntentProposal(
                    intent_type="VIEW_SERVICE",
                    label=str(first.get("label") or "查看事项")[:80],
                    section="services",
                    prefill=self._safe_prefill("services", suggested_actions),
                )
        return None

    @staticmethod
    def _safe_prefill(
        section: str, suggested_actions: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if section != "services" or len(suggested_actions) != 1:
            return {}
        service_id = str(suggested_actions[0].get("service_id", ""))
        try:
            return {"service_id": str(UUID(service_id))}
        except (ValueError, TypeError, AttributeError):
            return {}
