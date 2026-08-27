from __future__ import annotations

import json

from app.config import Settings, get_settings
from app.domain.enums import MaterialTemplateMode
from app.infrastructure.material_documents import (
    MaterialTemplateError,
    MaterialTemplatePack,
)


def check_material_template_pack(settings: Settings) -> tuple[int, int]:
    """Validate the local reviewed pack without database or model access."""

    if not settings.material_documents_enabled:
        raise MaterialTemplateError("material_documents_disabled")
    templates = MaterialTemplatePack(
        settings.material_template_manifest_path,
        settings.material_template_source_prefix,
    ).load()
    generatable = tuple(
        item
        for item in templates
        if item.mode is not MaterialTemplateMode.NOT_GENERATABLE
    )
    if not generatable:
        raise MaterialTemplateError("template_pack_sources_empty")
    return len(templates), len(generatable)


def main() -> None:
    templates, generatable = check_material_template_pack(get_settings())
    print(
        json.dumps(
            {
                "status": "ok",
                "templates": templates,
                "generatable": generatable,
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
