from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.application.material_documents import TemplateAnalysis
from app.domain.enums import MaterialTemplateMode
from app.infrastructure.material_documents import (
    DeterministicDocxMaterialRenderer,
    MaterialTemplatePack,
    validate_docx_package,
)


SYNTHETIC_FIELDS = {
    "applicant_name": "演示申请人甲",
    "contact_phone": "13800000000",
    "verification.loss_date": "2026年8月20日",
    "verification.loss_place": "成都市演示服务大厅",
    "verification.loss_description": "演示出行途中发现证件遗失，现申请补领。",
    "business.name": "成都未来演示科技有限公司",
    "business.unified_social_credit_code": "91510100DEMO000001",
    "business.parent_name": "四川未来演示集团有限公司",
    "business.parent_unified_social_credit_code": "91510000DEMO000002",
    "business.branch_relationship_description": "本单位为上级演示主体依法设立的分支机构，仅用于学生项目演示。",
    "application.agent_name": "演示代理人乙",
    "application.agent_demo_id": "DEMO-ID-AGENT-001",
    "application.authorization_scope": "代为提交演示申请并查询办理状态",
    "application.authorization_end_date": "2026年12月31日",
    "operator.name": "演示经办人丙",
    "operator.demo_id": "DEMO-ID-OPERATOR-001",
    "operator.authorization_scope": "代为办理本次项目演示事项",
    "operator.authorization_end_date": "2026年12月31日",
    "contract.employee_name": "演示员工丁",
    "contract.employee_demo_id": "DEMO-ID-EMPLOYEE-001",
    "contract.effective_date": "2026年9月1日",
    "contract.end_date": "2027年8月31日",
    "contract.work_role": "演示产品助理",
    "contract.work_location": "成都市演示办公区",
    "contract.demo_salary": "人民币 6000 元/月（演示）",
    "contract.collective_scope": "演示项目组全体合成人员",
    "contract.employee_count": "12",
    "fund.contribution_base": "5000",
    "fund.contribution_ratio": "8%",
    "fund.demo_personnel": (
        '[{"name":"演示员工甲","base":"5000","ratio":"8%","remark":"学生项目"},'
        '{"name":"演示员工乙","base":"5200","ratio":"8%","remark":"学生项目"}]'
    ),
    "fund.demo_bank_name": "演示银行成都分行",
    "fund.demo_account_name": "成都未来演示科技有限公司",
    "fund.demo_account_number": "DEMO-ACCOUNT-0001",
}


async def render_samples(manifest: str, source_prefix: str, output_dir: Path) -> int:
    pack = MaterialTemplatePack(manifest, source_prefix).load()
    renderer = DeterministicDocxMaterialRenderer()
    output_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for template in pack:
        if (
            template.mode is MaterialTemplateMode.NOT_GENERATABLE
            or template.source_bytes is None
        ):
            continue
        analysis = TemplateAnalysis(
            fields={
                key: SYNTHETIC_FIELDS[key]
                for key in template.allowed_fields
                if key in SYNTHETIC_FIELDS
            }
        )
        content = await renderer.render(
            mode=template.mode,
            template_key=template.template_key,
            template_title=template.title,
            source_docx=template.source_bytes,
            analysis=analysis,
        )
        validate_docx_package(content)
        (output_dir / f"{template.template_key}.docx").write_bytes(content)
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic DOCX samples for material-template visual QA"
    )
    parser.add_argument(
        "--manifest",
        default="resources/material_templates/v1/manifest.json",
    )
    parser.add_argument("--source-prefix", default="material-templates/v1")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    count = asyncio.run(
        render_samples(args.manifest, args.source_prefix, args.output_dir.resolve())
    )
    print(f"rendered {count} synthetic material document samples")


if __name__ == "__main__":
    main()
