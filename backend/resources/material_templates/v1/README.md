# Material template pack v1

This directory contains a small, reviewed template pack for the six seeded
demo services.  It never contains the raw split archive.

- `source-map.json` is the reviewed build input.  It maps every seeded material
  requirement, including explicit `NOT_GENERATABLE` evidence items.
- `manifest.json` is generated and is the stable runtime contract.
- `docx/` contains only normalized, hash-pinned DOCX references.

Build and verify with the bundled workspace Python runtime:

```powershell
$python = 'C:\Users\67673\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $python backend/tools/build_material_template_pack.py build `
  --archive '..\材料模板清单\申请材料 (2).zip' `
  --source-map backend/resources/material_templates/v1/source-map.json `
  --output-dir backend/resources/material_templates/v1
& $python backend/tools/build_material_template_pack.py verify `
  --manifest backend/resources/material_templates/v1/manifest.json
```

The builder streams only allow-listed entries from `.z01` and `.zip`, checks
CRC/size/path/encryption limits, rejects active or external OOXML content,
scrubs personal/machine metadata, and writes deterministic packages.  Every
packaged document carries the notice that it is only a student-demo template.
