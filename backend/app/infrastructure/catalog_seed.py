from __future__ import annotations

from typing import Final


DEMO_DELIVERY_OPTIONS: Final[dict[int, tuple[str, ...]]] = {
    1001: ("WINDOW_PICKUP", "DEMO_MAIL"),
    1002: ("WINDOW_PICKUP", "DEMO_MAIL"),
    1003: ("DIGITAL_RESULT", "WINDOW_PICKUP", "DEMO_MAIL"),
    1004: ("DIGITAL_RESULT",),
    1005: ("DIGITAL_RESULT",),
    1006: ("DIGITAL_RESULT",),
}


def demo_delivery_contract(
    external_item_id: int | None, delivery_supported: bool
) -> dict[str, object]:
    """Derive result channels without changing the already-applied schema.

    PostgreSQL's version switch can disable all result-delivery channels. When
    it is enabled, the mirrored external catalogue limits which channels the
    local adapter can actually provide. For an administrator-created local
    item, the switch explicitly enables local demo mail.
    """

    if not delivery_supported:
        options = ()
    elif external_item_id in DEMO_DELIVERY_OPTIONS:
        options = DEMO_DELIVERY_OPTIONS[external_item_id]  # type: ignore[index]
    else:
        options = ("DEMO_MAIL",)
    mail_supported = "DEMO_MAIL" in options
    return {
        "supported": bool(options),
        "options": list(options),
        "mail_supported": mail_supported,
        "demo_mail_supported": mail_supported,
    }


DEMO_DEPARTMENTS: Final = [
    {"code": "PUBLIC_SECURITY", "name": "演示市公安局"},
    {"code": "HUMAN_RESOURCES", "name": "演示市人力资源和社会保障局"},
    {"code": "MARKET_REGULATION", "name": "演示市市场监督管理局"},
    {"code": "HOUSING_FUND", "name": "演示市住房公积金管理中心"},
]


DEMO_WINDOWS: Final = [
    {"code": "POLICE-HUKOU-01", "department": "PUBLIC_SECURITY", "name": "演示市民服务中心户政窗口", "address": "演示大道 100 号 B 区 02 窗口", "latitude": 39.900202, "longitude": 116.400202, "appointment_supported": True},
    {"code": "HRSS-CENTER-01", "department": "HUMAN_RESOURCES", "name": "演示市民服务中心人社窗口", "address": "演示大道 100 号 A 区 01 窗口", "latitude": 39.900101, "longitude": 116.400101, "appointment_supported": True},
    {"code": "HRSS-BUSINESS-01", "department": "HUMAN_RESOURCES", "name": "演示市企业服务中心人社窗口", "address": "演示创新路 200 号 04 窗口", "latitude": 39.910404, "longitude": 116.410404, "appointment_supported": False},
    {"code": "LABOR-SERVICE-01", "department": "HUMAN_RESOURCES", "name": "演示市企业服务中心劳动关系窗口", "address": "演示创新路 200 号 05 窗口", "latitude": 39.910505, "longitude": 116.410505, "appointment_supported": False},
    {"code": "MARKET-CENTER-01", "department": "MARKET_REGULATION", "name": "演示市民服务中心市场监管窗口", "address": "演示大道 100 号 C 区 03 窗口", "latitude": 39.900303, "longitude": 116.400303, "appointment_supported": True},
    {"code": "FUND-CENTER-01", "department": "HOUSING_FUND", "name": "演示市民服务中心公积金窗口", "address": "演示大道 100 号 D 区 06 窗口", "latitude": 39.900606, "longitude": 116.400606, "appointment_supported": True},
]


def _schema(required: list[str], properties: dict[str, dict[str, str]] | None = None) -> dict[str, object]:
    base = {
        "applicant_name": {"type": "string", "title": "申请人/经办人姓名（合成演示）"},
        "contact_phone": {"type": "string", "title": "联系电话（合成演示）"},
    }
    return {"type": "object", "required": ["applicant_name", "contact_phone", *required], "properties": {**base, **(properties or {})}}


def _step(order: int, code: str, title: str, actor: str, description: str, duration: str) -> dict[str, object]:
    return {"order": order, "code": code, "title": title, "actor": actor, "description": description, "expected_duration": duration}


DEMO_SERVICES: Final = [
    {
        "external_item_id": 1001, "code": "DEMO-SS-CARD-001", "department": "HUMAN_RESOURCES", "window": "HRSS-CENTER-01", "applicant_type": "INDIVIDUAL",
        "title": "社会保障卡申领", "summary": "申领实体社会保障卡。所有内容均为联调演示数据，不可作为真实办事依据。",
        "form_schema": _schema([], {"applicant": {"type": "object"}}), "appointment_supported": True, "requires_appointment": False,
        "fee_required": False, "fee_cents": 0, "delivery_supported": True,
        "rules": [({"all": [{"exists": ["applicant.valid_identity_document"]}, {"eq": ["applicant.has_duplicate_demo_card", False]}]}, "需持有效身份证明且未重复申领")],
        "materials": [
            {"code": "ss-1", "name": "有效身份证件", "required": True},
            {"code": "ss-2", "name": "近期免冠照片", "required": True},
            {"code": "ss-3", "name": "监护关系证明", "required": False, "condition": {"eq": ["applicant.is_minor", True]}},
        ],
        "steps": [_step(1, "SUBMIT", "提交申请", "APPLICANT", "填写表单并上传演示材料。", "即时"), _step(2, "REVIEW", "材料审核", "STAFF", "工作人员核对申请信息和材料。", "3 个演示工作日"), _step(3, "PRODUCE", "模拟制卡", "SYSTEM", "生成演示制卡结果。", "6 个演示工作日"), _step(4, "DELIVER", "领取结果", "APPLICANT", "窗口领取或选择演示邮寄。", "1 个演示工作日")],
    },
    {
        "external_item_id": 1002, "code": "DEMO-ID-REISSUE-001", "department": "PUBLIC_SECURITY", "window": "POLICE-HUKOU-01", "applicant_type": "INDIVIDUAL",
        "title": "居民身份证丢失补领", "summary": "办理居民身份证丢失补领。所有身份核验、缴费和结果均为模拟。",
        "form_schema": _schema([], {"verification": {"type": "object"}}), "appointment_supported": True, "requires_appointment": True,
        "requires_verification": True, "fee_required": True, "fee_cents": 4000, "delivery_supported": True,
        "rules": [({"eq": ["verification.demo_identity_passed", True]}, "需完成演示身份核验")],
        "materials": [{"code": "id-1", "name": "居民户口簿或其他有效身份证明", "required": True}, {"code": "id-2", "name": "丢失情况说明", "required": True}, {"code": "id-3", "name": "原居民身份证", "required": False}],
        "steps": [_step(1, "APPOINT", "预约窗口", "APPLICANT", "选择演示窗口和可用时段。", "即时"), _step(2, "VERIFY", "身份核验", "SYSTEM", "仅推进模拟核验状态，不采集生物信息。", "即时"), _step(3, "REVIEW", "信息审核", "STAFF", "工作人员核对演示材料。", "3 个演示工作日"), _step(4, "PAY", "模拟缴费", "APPLICANT", "完成可失败重试的本地模拟支付。", "即时"), _step(5, "DELIVER", "领取结果", "APPLICANT", "窗口领取或选择演示邮寄。", "17 个演示工作日")],
    },
    {
        "external_item_id": 1003, "code": "DEMO-BL-REGISTER-001", "department": "MARKET_REGULATION", "window": "MARKET-CENTER-01", "applicant_type": "INDIVIDUAL",
        "title": "个体工商户设立登记", "summary": "办理个体工商户设立登记。登记结果和电子证照均为演示数据。",
        "form_schema": _schema(["business"], {"business": {"type": "object"}, "application": {"type": "object"}}), "appointment_supported": True, "requires_appointment": False,
        "fee_required": False, "fee_cents": 0, "delivery_supported": True,
        "rules": [({"all": [{"eq": ["applicant.has_civil_capacity", True]}, {"exists": ["business.premises_address"]}]}, "需具备民事行为能力并填写经营场所")],
        "materials": [{"code": "bl-1", "name": "经营者身份证明", "required": True}, {"code": "bl-2", "name": "经营场所使用证明", "required": True}, {"code": "bl-3", "name": "委托代理证明", "required": False, "condition": {"eq": ["application.submitted_by_agent", True]}}],
        "steps": [_step(1, "PRECHECK", "信息预检", "SYSTEM", "校验演示名称、经营范围和地址字段。", "即时"), _step(2, "SUBMIT", "提交申请", "APPLICANT", "确认表单及材料完整性。", "即时"), _step(3, "REVIEW", "登记审核", "STAFF", "市场监管工作人员执行演示审核。", "2 个演示工作日"), _step(4, "DELIVER", "领取结果", "APPLICANT", "下载演示电子结果或选择线下方式。", "1 个演示工作日")],
    },
    {
        "external_item_id": 1004, "code": "DEMO-ENTERPRISE-SS-001", "department": "HUMAN_RESOURCES", "window": "HRSS-BUSINESS-01", "applicant_type": "ENTERPRISE",
        "title": "企业社会保险登记", "summary": "为企业办理社会保险登记。企业、人员和登记结果均为合成演示数据。",
        "form_schema": _schema(["business", "operator"], {"business": {"type": "object"}, "operator": {"type": "object"}}), "appointment_supported": False, "requires_appointment": False,
        "fee_required": False, "fee_cents": 0, "delivery_supported": True,
        "rules": [({"all": [{"eq": ["business.registration_status", "ACTIVE"]}, {"eq": ["operator.authorized", True]}]}, "企业需正常登记且经办人已获授权")],
        "materials": [{"code": "ess-1", "name": "企业登记信息页", "required": True}, {"code": "ess-2", "name": "经办人授权书", "required": True}, {"code": "ess-3", "name": "分支机构关系说明", "required": False, "condition": {"eq": ["business.is_branch", True]}}],
        "steps": [_step(1, "PRECHECK", "企业资格预检", "SYSTEM", "校验演示企业状态和经办授权。", "即时"), _step(2, "SUBMIT", "提交登记", "APPLICANT", "提交企业与用工信息。", "即时"), _step(3, "REVIEW", "登记审核", "STAFF", "人社工作人员处理演示待办。", "2 个演示工作日"), _step(4, "RESULT", "生成回执", "SYSTEM", "生成演示电子回执。", "即时")],
    },
    {
        "external_item_id": 1005, "code": "DEMO-LABOR-CONTRACT-001", "department": "HUMAN_RESOURCES", "window": "LABOR-SERVICE-01", "applicant_type": "ENTERPRISE",
        "title": "劳动合同备案", "summary": "提交劳动合同备案并跟踪审核结果。合同与人员信息必须为合成演示数据。",
        "form_schema": _schema(["business", "contract"], {"business": {"type": "object"}, "contract": {"type": "object"}}), "appointment_supported": False, "requires_appointment": False,
        "fee_required": False, "fee_cents": 0, "delivery_supported": True,
        "rules": [({"all": [{"eq": ["business.demo_social_insurance_registered", True]}, {"exists": ["contract.employee_demo_id"]}, {"exists": ["contract.effective_date"]}]}, "需完成演示社保登记并填写合同必要字段")],
        "materials": [{"code": "lc-1", "name": "劳动合同演示件", "required": True}, {"code": "lc-2", "name": "企业经办人授权书", "required": True}, {"code": "lc-3", "name": "集体合同说明", "required": False, "condition": {"eq": ["contract.type", "COLLECTIVE"]}}],
        "steps": [_step(1, "PRECHECK", "资格预检", "SYSTEM", "检查企业状态和必要字段。", "即时"), _step(2, "SUBMIT", "提交备案", "APPLICANT", "上传合成合同材料并提交。", "即时"), _step(3, "REVIEW", "备案审核", "STAFF", "工作人员批准或要求补正。", "1 个演示工作日"), _step(4, "RESULT", "生成结果", "SYSTEM", "生成演示备案编号和电子回执。", "即时")],
    },
    {
        "external_item_id": 1006, "code": "DEMO-HOUSING-FUND-001", "department": "HOUSING_FUND", "window": "FUND-CENTER-01", "applicant_type": "ENTERPRISE",
        "title": "单位住房公积金缴存登记与演示缴付", "summary": "完成单位缴存登记并体验金额计算和模拟缴付，不连接真实公积金或银行系统。",
        "form_schema": _schema(["business", "fund"], {"business": {"type": "object"}, "fund": {"type": "object"}}), "appointment_supported": True, "requires_appointment": False,
        "fee_required": True, "fee_cents": 0, "fee_calculation": "演示缴存基数 × 演示缴存比例，仅生成模拟支付订单", "delivery_supported": True,
        "rules": [({"all": [{"eq": ["business.registration_status", "ACTIVE"]}, {"exists": ["fund.contribution_base"]}, {"gte": ["fund.contribution_ratio", 0.05]}, {"lte": ["fund.contribution_ratio", 0.12]}]}, "单位状态、缴存基数和比例需符合演示规则")],
        "materials": [{"code": "hf-1", "name": "单位登记信息页", "required": True}, {"code": "hf-2", "name": "缴存人员汇总表", "required": True}, {"code": "hf-3", "name": "委托扣款授权演示件", "required": False, "condition": {"eq": ["fund.payment_mode", "DEMO_DEBIT"]}}],
        "steps": [_step(1, "PRECHECK", "单位资格预检", "SYSTEM", "校验演示单位状态、基数和比例。", "即时"), _step(2, "SUBMIT", "提交登记", "APPLICANT", "提交单位及合成人员汇总信息。", "即时"), _step(3, "REVIEW", "登记审核", "STAFF", "公积金工作人员处理演示待办。", "2 个演示工作日"), _step(4, "PAY", "模拟缴付", "APPLICANT", "生成并推进本地模拟支付订单。", "即时"), _step(5, "RESULT", "生成凭证", "SYSTEM", "生成演示电子凭证。", "即时")],
    },
]
