from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import zipfile

import pytest


TOOL_PATH = Path(__file__).parents[1] / "tools" / "build_material_template_pack.py"
SPEC = importlib.util.spec_from_file_location("material_template_pack_tool", TOOL_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _docx(parts: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, payload in parts.items():
            archive.writestr(name, payload)
    return output.getvalue()


def _minimal_parts() -> dict[str, bytes]:
    return {
        "[Content_Types].xml": b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        "_rels/.rels": b'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/document.xml": b'<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p w:rsidR="DEADBEEF"><w:r><w:t>demo</w:t></w:r></w:p></w:body></w:document>',
    }


def test_sanitize_is_deterministic_and_removes_rsid() -> None:
    source = _docx(_minimal_parts())
    first = MODULE.sanitize_docx(source, "fixture.docx")
    second = MODULE.sanitize_docx(source, "fixture.docx")
    assert first == second
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        assert b"rsidR" not in archive.read("word/document.xml")


def test_sanitize_rejects_external_relationship() -> None:
    parts = _minimal_parts()
    parts["word/_rels/document.xml.rels"] = b'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.test" TargetMode="External"/></Relationships>'
    with pytest.raises(MODULE.PackBuildError, match="external relationship"):
        MODULE.sanitize_docx(_docx(parts), "external.docx")


def test_sanitize_rejects_active_content() -> None:
    parts = _minimal_parts()
    parts["word/vbaProject.bin"] = b"not-a-macro"
    with pytest.raises(MODULE.PackBuildError, match="active or opaque"):
        MODULE.sanitize_docx(_docx(parts), "macro.docx")


def test_source_map_covers_seeded_requirements_once() -> None:
    path = Path(__file__).parents[1] / "resources" / "material_templates" / "v1" / "source-map.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    pairs = [(item["service_code"], item["requirement_code"]) for item in payload["templates"]]
    assert len(pairs) == 18
    assert len(set(pairs)) == 18
    assert {item["requirement_code"] for item in payload["templates"] if item["mode"] != "NOT_GENERATABLE"} == {
        "id-2",
        "bl-3",
        "ess-2",
        "ess-3",
        "lc-1",
        "lc-2",
        "lc-3",
        "hf-2",
        "hf-3",
    }
