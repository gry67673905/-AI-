# docs(materials): 补录文档完整性与恢复验收

> 课程验收补录 / retrospective evidence：内容依据仓库在 GitHub 实际创建时的代码、接口、文档与测试整理；它不倒填历史日期、不伪造原开发过程，完成与未完成状态均按证据如实标注。

## 证据边界

本文件针对“材料模板与 DOCX”整理当前仓库可核查事实；它不是原开发日期的伪造记录。

### 关联路径

- `backend/app/application/material_documents.py`
- `backend/app/ops/material_document_worker.py`
- `backend/resources/material_templates/v1/manifest.json`
- `backend/tests/test_material_documents.py`

### 关联接口或符号

- `MaterialDocumentCoordinator`
- `MaterialDocumentWorker`
- `DeterministicDocxMaterialRenderer`
- `GET /api/v1/applications/{application_id}/material-template-options`
- `POST /api/v1/applications/{application_id}/material-documents`
- `GET /api/v1/material-documents/{generation_id}/download`

## 生成验收

记录模板哈希、字段投影、OOXML 结构、文件大小和 SHA-256 检查。

## 并发与恢复

覆盖幂等创建、单租约处理、租约过期回收、失败状态和任务过期。

## 访问控制

记录跨账号、未就绪、过期及完整性失败时的下载拒绝。
