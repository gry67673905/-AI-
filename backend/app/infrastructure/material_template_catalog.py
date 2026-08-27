from __future__ import annotations

from dataclasses import replace
from pathlib import PurePosixPath

from app.infrastructure.material_documents import PackedMaterialTemplate


MATERIAL_TEMPLATE_PACK_VERSION = 1


def immutable_material_template_objects(
    templates: tuple[PackedMaterialTemplate, ...],
) -> tuple[PackedMaterialTemplate, ...]:
    """Return reviewed templates with immutable, content-addressed object keys."""

    result: list[PackedMaterialTemplate] = []
    for template in templates:
        if template.source_object_key is None or template.source_sha256 is None:
            result.append(template)
            continue
        parent = PurePosixPath(template.source_object_key).parent.as_posix().rstrip("/")
        object_key = (
            f"{parent}/{template.template_key}/"
            f"v{MATERIAL_TEMPLATE_PACK_VERSION}/{template.source_sha256}.docx"
        )
        result.append(replace(template, source_object_key=object_key))
    return tuple(result)
