# docs(materials): 记录受控 DOCX 生成实现

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

## 模板来源

说明版本化模板包、manifest、哈希校验和视觉结构分析的职责。

## 任务执行

记录 API 入队、worker 租约、确定性渲染、私有 MinIO 存储和状态转换。

## 下载边界

说明所有者、状态、有效期、大小、SHA-256 和 OOXML 完整性检查。
