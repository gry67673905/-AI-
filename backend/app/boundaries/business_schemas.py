from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.enums import ApplicantType, Role
from app.domain.policies import DomainRuleViolation, FormValidationService


T = TypeVar("T")


class ListResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int


class UserView(BaseModel):
    id: UUID
    username: str
    display_name: str
    role: Role
    applicant_type: ApplicantType | None = None
    active: bool = True
    department_id: UUID | None = None
    demo_data: bool = True


class RequestCodeRequest(BaseModel):
    destination: str = Field(min_length=3, max_length=100)
    purpose: Literal["REGISTER", "LOGIN", "RESET"] = "REGISTER"


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)
    applicant_type: ApplicantType
    verification_code: str = Field(default="000000", min_length=4, max_length=12)
    synthetic_data_confirmed: bool = True

    @field_validator("synthetic_data_confirmed")
    @classmethod
    def require_demo_data(cls, value: bool) -> bool:
        if not value:
            raise ValueError("本地演示只允许使用合成数据")
        return value


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=512)


class LogoutRequest(RefreshRequest):
    pass


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserView


class ServiceSummary(BaseModel):
    id: UUID
    external_item_id: int | None = None
    code: str
    title: str
    summary: str
    applicant_type: ApplicantType
    status: str
    fee_cents: int = 0
    fee_required: bool = False
    fee_calculation: str | None = None
    appointment_supported: bool = False
    requires_appointment: bool = False
    requires_verification: bool = False
    delivery_supported: bool = False
    delivery_options: list[str] = Field(default_factory=list)
    mail_supported: bool = False
    demo_mail_supported: bool = False
    demo_data: bool = True


class EligibilityRequest(BaseModel):
    answers: dict[str, Any] = Field(default_factory=dict)


class MaterialEvaluationRequest(EligibilityRequest):
    pass


class DraftApplicationRequest(BaseModel):
    service_id: UUID
    initial_form_data: dict[str, Any] = Field(default_factory=dict)


class FormUpdateRequest(BaseModel):
    data: dict[str, Any]
    version: int = Field(ge=1)


class ApplicationView(BaseModel):
    id: UUID
    service_id: UUID
    service_version_id: UUID
    applicant_id: UUID
    status: str
    form_data: dict[str, Any]
    version: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
    demo_data: bool = True


class StatusWriteRequest(BaseModel):
    version: int = Field(ge=1)
    comment: str | None = Field(default=None, max_length=1000)


class ReviewDecisionRequest(StatusWriteRequest):
    require_payment: bool = False


class FeedbackRequest(BaseModel):
    session_id: UUID
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class HandoffCreateRequest(BaseModel):
    session_id: UUID
    subject: str = Field(min_length=1, max_length=200)
    department_id: UUID | None = None


class HandoffMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class AppointmentCreateRequest(BaseModel):
    service_id: UUID
    window_id: UUID
    slot_start: datetime

    @field_validator("slot_start")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("预约时间必须包含时区")
        return value.astimezone(timezone.utc)


class AppointmentAdvanceRequest(BaseModel):
    status: Literal["COMPLETED", "NO_SHOW"]


class PaymentCreateRequest(BaseModel):
    application_id: UUID


class PaymentAdvanceRequest(BaseModel):
    outcome: Literal["success", "failure"] = "success"


class VerificationCreateRequest(BaseModel):
    application_id: UUID


class VerificationCompleteRequest(BaseModel):
    outcome: Literal["pass", "fail"] = "pass"


class DeliveryCreateRequest(BaseModel):
    recipient: str = Field(min_length=1, max_length=100)
    address: str = Field(min_length=3, max_length=255)


class DeliveryAdvanceRequest(BaseModel):
    status: Literal["DISPATCHED", "DELIVERED"]


class DepartmentCreateRequest(BaseModel):
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=1, max_length=120)


class WindowCreateRequest(BaseModel):
    department_id: UUID
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=1, max_length=120)
    address: str = Field(min_length=3, max_length=255)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    opening_hours: str = Field(default="工作日 09:00-17:00", max_length=120)
    capacity_per_slot: int = Field(default=10, ge=1, le=1000)


class StaffCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)
    department_id: UUID
    window_id: UUID | None = None


class AccountStatusRequest(BaseModel):
    active: bool


class EligibilityRuleInput(BaseModel):
    rule: dict[str, Any]
    failure_message: str = Field(default="未满足办理条件", min_length=1, max_length=255)

    @model_validator(mode="before")
    @classmethod
    def accept_direct_rule(cls, value: Any) -> Any:
        # Preserve the earlier compact API shape while ensuring the repository
        # always receives one normalized object with a required ``rule`` key.
        if isinstance(value, dict) and "rule" not in value:
            return {"rule": value}
        return value


class MaterialRequirementInput(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=200)
    required: bool = True
    condition: dict[str, Any] | None = None
    accepted_types: list[
        Literal["application/pdf", "image/jpeg", "image/png"]
    ] = Field(
        default_factory=lambda: ["application/pdf", "image/jpeg", "image/png"],
        min_length=1,
    )

    @field_validator("accepted_types")
    @classmethod
    def unique_accepted_types(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("材料格式不能重复")
        return value


class ProcessStepInput(BaseModel):
    order: int | None = Field(default=None, ge=1)
    code: str | None = Field(
        default=None, min_length=1, max_length=40,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    title: str = Field(min_length=1, max_length=120)
    actor: Literal["APPLICANT", "STAFF", "SYSTEM", "ADMIN"] = "SYSTEM"
    description: str = Field(default="", max_length=4000)
    expected_duration: str = Field(default="即时", min_length=1, max_length=80)


class ServiceVersionPayload(BaseModel):
    _supported_fee_calculations: ClassVar[set[str]] = {
        "DEMO_CONTRIBUTION_BASE_TIMES_RATIO",
        "演示缴存基数 × 演示缴存比例，仅生成模拟支付订单",
    }
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=4000)
    form_schema: dict[str, Any] = Field(default_factory=dict)
    fee_cents: int = Field(default=0, ge=0, le=10_000_000)
    fee_required: bool = False
    fee_calculation: str | None = Field(default=None, max_length=500)
    appointment_supported: bool = False
    requires_appointment: bool = False
    requires_verification: bool = False
    delivery_supported: bool = False
    eligibility_rules: list[EligibilityRuleInput] = Field(default_factory=list)
    materials: list[MaterialRequirementInput] = Field(default_factory=list)
    process_steps: list[ProcessStepInput] = Field(default_factory=list)

    @field_validator("form_schema")
    @classmethod
    def validate_form_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            FormValidationService.validate_schema(value)
        except DomainRuleViolation as exc:
            raise ValueError(str(exc)) from exc
        return value

    @model_validator(mode="after")
    def validate_cross_field_contract(self) -> "ServiceVersionPayload":
        if self.requires_appointment and not self.appointment_supported:
            raise ValueError("要求预约的事项必须同时启用预约能力")
        if self.fee_required:
            if self.fee_cents <= 0 and self.fee_calculation not in self._supported_fee_calculations:
                raise ValueError("要求缴费时必须配置正金额或受支持的演示计算规则")
            if self.fee_cents > 0 and self.fee_calculation is not None:
                raise ValueError("固定金额与演示计算规则不能同时配置")
        elif self.fee_cents > 0 or self.fee_calculation is not None:
            raise ValueError("无需缴费的事项不能配置金额或计算规则")
        material_codes = [item.code for item in self.materials]
        if len(material_codes) != len(set(material_codes)):
            raise ValueError("材料编码不能重复")
        for index, step in enumerate(self.process_steps, start=1):
            if step.order is None:
                step.order = index
            if step.code is None:
                step.code = f"STEP_{index}"
        step_orders = [item.order for item in self.process_steps]
        step_codes = [item.code for item in self.process_steps]
        if len(step_orders) != len(set(step_orders)):
            raise ValueError("流程步骤顺序不能重复")
        if len(step_codes) != len(set(step_codes)):
            raise ValueError("流程步骤编码不能重复")
        return self


class ServiceCreateRequest(ServiceVersionPayload):
    code: str = Field(min_length=2, max_length=64)
    department_id: UUID
    window_id: UUID | None = None
    applicant_type: ApplicantType


class ServiceVersionCreateRequest(ServiceVersionPayload):
    pass


class LifecycleRequest(BaseModel):
    target_status: Literal["PUBLISHED", "SUSPENDED", "RETIRED"]
    version_id: UUID | None = None


class KnowledgeUploadMetadata(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    source: str = Field(default="demo://admin-upload", max_length=255)
