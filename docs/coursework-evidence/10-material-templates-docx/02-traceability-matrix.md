# docs(materials): 建立模板生成模式追踪矩阵

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

## APPLICATION 模式

追踪办件、材料要求、模板选项、允许字段快照和 generation_id。

## CONSULTATION 模式

追踪会话候选、显式确认、空字段快照和不创建办件的约束。

## 共享 worker

说明两种模式如何共享任务租约、模板包、渲染、状态查询和私有下载。
