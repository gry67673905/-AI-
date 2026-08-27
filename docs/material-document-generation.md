# 材料 Word 模板生成

## 范围

该能力面向已登录群众，支持两种互不替代的生成模式。`APPLICATION` 模式仍只用于草稿或待补正办件，并使用办件中的合成演示表单值预填可编辑 DOCX；`CONSULTATION` 模式由普通 AI 咨询中的模板卡发起，不创建办件，只生成空字段、可由用户自行填写的模板。证件、照片、关系证明、权属证明等证据材料明确标记为 `NOT_GENERATABLE`，不能由模型生成。生成件统一显示“演示模板，仅供项目填写演示，不作为正式政务表格”。

咨询模式中，模型只能将自然语言请求归为“查询模板、要求生成或澄清选择”；事项、模板、意图和任务 ID 均由后端的受控目录决定。用户问“有没有模板”时只看到模板卡；必须点击生成并在确认层显式确认后，才会创建任务。匿名用户可以查看模板信息，但会收到登录提示，不能创建任务。

MCP 保持政务目录查询的只读边界；不会新增 `generate_docx` 等写工具，也不会让 DOCX、对象键或下载地址经过模型或 MCP。

原始 2.48 GiB 分卷归档只用于本地挑选模板，禁止上传云端。运行时只使用经过审查、净化和 SHA-256 固定的小型模板包：

- `backend/resources/material_templates/v1/source-map.json`：六个演示事项 18 个材料项的审查映射；
- `backend/resources/material_templates/v1/manifest.json`：运行时目录与来源/成品哈希；
- `backend/resources/material_templates/v1/docx/`：5 个允许的版式参考或可编辑来源。

## 调用流程

1. `APPLICATION`：Android 以办件 UUID 请求 `GET /api/v1/applications/{application_id}/material-template-options`，用户选择可生成材料并提交 `POST /api/v1/applications/{application_id}/material-documents`；请求必须带 `Idempotency-Key`。
2. `CONSULTATION`：普通咨询的 SSE `done.ui_cards` 返回不透明的模板意图；登录用户调用 `POST /api/v1/consultations/{session_id}/material-intents/{intent_id}/confirm`，同样必须带 `Idempotency-Key`。重复确认返回同一任务，不会重复扣减额度。
3. API 校验群众身份、办件所有者或咨询会话所有者、模板/材料关联和意图有效期。`APPLICATION` 只把白名单合成字段写入短期任务快照；`CONSULTATION` 写入空字段快照，返回 `202 + generation_id`。
4. 独立 `material-worker` 用 PostgreSQL `SKIP LOCKED` 获取单次租约，将审查过的 DOCX 渲染为最多 12 张页面图，只调用一次 `qwen3-vl-flash-2026-01-22`。不重试、不降级、不调用第二个模型。
5. 模型只能返回 `{fields, warnings}`，字段名必须属于模板白名单。正文、声明条款、授权范围结构、表格列和 OOXML 全部由后端固定渲染器控制；`SOURCE_EDITABLE` 只填写明确占位符或保守匹配的标签空位。
6. Android 可对多个 `generation_id` 分别以 2 秒/5 秒节奏请求 `GET /api/v1/material-documents/{generation_id}`。就绪后原生网关从固定下载路径取得 DOCX，校验 MIME、10 MiB 上限、SHA-256、OOXML 结构、压缩展开上限及活动/外部内容。
7. 用户通过 Android Storage Access Framework 自选位置保存；WebView 只传不透明 `generation_id`，不能传 URL、路径或 Intent。

## 数据和清理

- 生成文件只写入专用私有 MinIO bucket `smart-gov-generated-documents`，不生成预签名或公共 URL。上传材料、知识、模板源和生成文件四个 bucket 必须两两不同；启动配置和云端 preflight 均会阻止复用。
- 成功或失败后立即清空办件字段快照和补充要求；数据库只保留状态、哈希、大小、模型名和短警告。
- 咨询原文、历史回答和个人信息永不进入 `CONSULTATION` 任务字段快照或 Worker；Worker 只接收固定模板结构及空字段集合。
- 任务和下载对象 24 小时后过期。Worker 主动领取并删除对象，专用 bucket 另有 1 天生命周期作为孤儿清理安全网。
- 备份包含上传材料、知识对象和经审查模板源；24 小时生成 bucket 是可重建的临时输出，明确不进入备份。
- Word 不可直接作为现有办件材料上传；现有上传接口仍只接受 PDF/JPEG/PNG。

## 配置

API 与 Worker 共用以下非秘密配置：

```text
MATERIAL_DOCUMENTS_ENABLED=true
MATERIAL_TEMPLATE_PROVIDER=mock|dashscope
MATERIAL_TEMPLATE_MODEL=qwen3-vl-flash-2026-01-22
MATERIAL_TEMPLATE_DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MATERIAL_TEMPLATE_MANIFEST_PATH=resources/material_templates/v1/manifest.json
MATERIAL_TEMPLATE_SOURCE_PREFIX=material-templates/v1
MATERIAL_TEMPLATES_BUCKET=smart-gov-material-templates
GENERATED_DOCUMENTS_BUCKET=smart-gov-generated-documents
MATERIAL_DOCUMENT_RETENTION_HOURS=24
MATERIAL_DOCUMENT_USER_DAILY_LIMIT=10
MATERIAL_DOCUMENT_USER_ACTIVE_LIMIT=2
MATERIAL_DOCUMENT_GLOBAL_DAILY_LIMIT=20
MATERIAL_DOCUMENT_GLOBAL_QUEUE_LIMIT=50
```

全局每日额度按 UTC 的任务 `created_at` 计数，成功、失败或过期任务都会占用当日额度，避免多账号绕过成本上限。发布 lane 由 Compose 固定：本地为 `local`，云端 API 与 Worker 使用同一 `RELEASE_TAG`；它不是用户可调的业务参数。

云端 DashScope Key 只以 Docker secret 文件挂载到 Worker。当前 MetaStudio 覆盖复用服务器上的 `vision_dashscope_api_key` 文件；密钥不会进入 API 响应、Android、WebView、Compose 环境明文或仓库。

本地默认 `MATERIAL_TEMPLATE_PROVIDER=mock`，只用于流程和版式测试，不产生外部请求。生成合成 QA 样例：

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m tools.render_material_document_samples `
  --output-dir ..\artifacts\material-document-samples
```

模板包重建与验证命令见 `backend/resources/material_templates/v1/README.md`。

## 部署门禁

候选发布同时启动 `api-candidate` 和 `material-worker-candidate`。任务持久化 release lane，Worker 只领取自身 `RELEASE_TAG` 的任务；旧规范 Worker 不会把候选慢任务标记为中断。两者健康、迁移到 Alembic head `0009_consultation_materials`、模板导入、私有下载与一次真实生成通过后，才允许把 Nginx 切到 `127.0.0.1:18001`。规范端口发布完成后再切回 `18000` 并删除候选容器。任何真实模型失败都把任务标记为 `FAILED`，不会伪造模板或静默改用 Mock。
