# API 示例

以下示例面向本地 `http://127.0.0.1:8000`。所有 UUID、账号、表单、材料和操作结果都必须是合成演示数据。不要把 `.env` 中的密码或 Bearer Token 写进脚本、截图、日志或提交历史。

启动后可在 `http://127.0.0.1:8000/docs` 查看当前 OpenAPI；本文仅展示常用调用和约束。

## 公共接口

### 存活检查

```http
GET /health/live
```

该接口只证明 FastAPI 进程可响应，不检查数据库或其他依赖。

### 就绪检查

```http
GET /health/ready
```

```json
{
  "status": "ready",
  "checks": {
    "postgres": { "status": "ok", "latency_ms": 3 },
    "redis": { "status": "ok", "latency_ms": 1 },
    "milvus": { "status": "ok", "latency_ms": 9 },
    "mcp": { "status": "ok", "latency_ms": 4 },
    "mock_gov_api": { "status": "ok", "latency_ms": 2 },
    "minio": { "status": "ok", "latency_ms": 2 },
    "business_seed": { "status": "ok", "latency_ms": 4 }
  }
}
```

上例是默认本地模式的 7 项检查。固定团队 RAG 启用后，`checks` 还必须包含第 8 项 `rag_corpus`；该探针不调用付费 embedding，而是验证 dataset `team-2026-08-22-v1` 的内容/路由 alias 及 15,858/1,012 精确行数。团队语料导入是服务器运维命令，不新增 HTTP API，因此下方 OpenAPI 总数仍为 73。

### 搜索事项

```http
GET /api/v1/services?q=身份证
```

响应使用统一列表封包：

```json
{
  "items": [
    {
      "id": "<service_uuid>",
      "external_item_id": 1002,
      "code": "DEMO-ID-REISSUE-001",
      "title": "居民身份证丢失补领",
      "applicant_type": "INDIVIDUAL",
      "status": "PUBLISHED",
      "fee_required": true,
      "fee_cents": 4000,
      "appointment_supported": true,
      "requires_appointment": true,
      "requires_verification": true,
      "delivery_supported": true,
      "delivery_options": ["WINDOW_PICKUP", "DEMO_MAIL"],
      "mail_supported": true,
      "demo_mail_supported": true,
      "demo_data": true
    }
  ],
  "total": 1
}
```

事项子资源：

```http
GET  /api/v1/services/{service_id}
POST /api/v1/services/{service_id}/eligibility
GET  /api/v1/services/{service_id}/materials
POST /api/v1/services/{service_id}/materials/evaluate
GET  /api/v1/services/{service_id}/process
GET  /api/v1/services/{service_id}/form
GET  /api/v1/services/{service_id}/windows
```

资格预检请求：

```json
{
  "answers": {
    "verification": { "demo_identity_passed": true }
  }
}
```

结果 `outcome` 为 `ELIGIBLE`、`INELIGIBLE` 或 `NEEDS_INFORMATION`，并返回 `reasons`、`missing_fields` 和“不是正式审批结论”的 `disclaimer`。

### 普通 AI 咨询

```http
POST /api/v1/chat
Content-Type: application/json

{
  "message": "居民身份证补领需要哪些演示材料？",
  "service_id": "<service_uuid>"
}
```

`session_id`、`service_id` 和 `application_id` 均可选；只有授权登录用户可带 `application_id`。响应示意：

```json
{
  "request_id": "<request_uuid>",
  "session_id": "<session_uuid>",
  "answer": "<模型生成的演示说明>",
  "sources": [
    { "kind": "local_catalog", "title": "居民身份证丢失补领（本地演示事项）", "reference": "local-catalog://services/<service_uuid>", "excerpt": "..." },
    { "kind": "mcp", "title": "事项详情", "reference": "mcp:get_service_details", "excerpt": "..." },
    { "kind": "rag", "title": "居民身份证补领（演示）", "reference": "demo://knowledge/id-card-replacement", "excerpt": "..." }
  ],
  "tool_calls": [],
  "cache_hit": false,
  "warnings": [],
  "candidate_services": [],
  "suggested_actions": [],
  "clarification_required": false,
  "handoff_status": null
}
```

`local_catalog` 只由协调者从 PostgreSQL 当前已发布版本的白名单公开字段生成；`mcp` 来自外部模拟目录，`rag` 来自 ACTIVE 知识块。三者用途不同，不能互相伪装。如果“社保”等问题匹配多个事项，接口返回候选和 `SELECT_SERVICE` 建议，不调用检索或模型猜测第一项。

### SSE 咨询

```http
POST /api/v1/chat/stream
Accept: text/event-stream
Content-Type: application/json

{ "message": "社会保障卡怎么办？", "service_id": "<service_uuid>" }
```

事件顺序固定：

```text
event: meta
data: {"request_id":"...","session_id":"...","sources":[],"candidate_services":[],"clarification_required":false,"demo_data":true}

event: delta
data: {"text":"增量文本"}

event: done
data: {"request_id":"...","session_id":"...","warnings":[],"suggested_actions":[]}
```

失败通过 `event: error` 返回 `{ "code": "...", "message": "..." }`，客户端不应把 HTTP 连接结束当成完整答案。

## 认证

### 演示验证码与注册

```http
POST /api/v1/auth/request-code
Content-Type: application/json

{ "destination": "demo-contact", "purpose": "REGISTER" }
```

本地 Provider 返回掩码目标和演示码，不发送真实短信。

```http
POST /api/v1/auth/register
Content-Type: application/json

{
  "username": "synthetic.citizen.001",
  "password": "<仅在本地内存中生成的强密码>",
  "display_name": "合成演示用户",
  "applicant_type": "INDIVIDUAL",
  "verification_code": "<本地演示码>",
  "synthetic_data_confirmed": true
}
```

企业注册只把 `applicant_type` 改为 `ENTERPRISE`。工作人员和管理员不能公开注册。

### 登录与令牌

```http
POST /api/v1/auth/login
Content-Type: application/json

{ "username": "<local_demo_username>", "password": "<local_demo_password>" }
```

```json
{
  "access_token": "<keep_in_native_memory_or_keystore>",
  "refresh_token": "<keep_in_native_keystore>",
  "token_type": "bearer",
  "expires_in": 900,
  "user": { "id": "...", "role": "CITIZEN", "applicant_type": "INDIVIDUAL", "demo_data": true }
}
```

```http
POST /api/v1/auth/refresh
{ "refresh_token": "<refresh_token>" }

POST /api/v1/auth/logout
{ "refresh_token": "<refresh_token>" }

GET /api/v1/auth/me
Authorization: Bearer <access_token>
```

refresh 会轮换令牌；登出、账号冻结或 `token_version` 变化后旧令牌失效。

## 群众办件

以下所有调用都需要 `Authorization: Bearer <citizen_access_token>`。写操作使用新的 `Idempotency-Key`；表单/状态写入使用最新 `version`。

### 创建与更新草稿

```http
POST /api/v1/applications
Authorization: Bearer <token>
Idempotency-Key: <uuid>
Content-Type: application/json

{
  "service_id": "<service_uuid>",
  "initial_form_data": {
    "applicant_name": "合成演示申请人",
    "contact_phone": "00000000000",
    "applicant": {
      "valid_identity_document": true,
      "has_duplicate_demo_card": false,
      "is_minor": false
    }
  }
}
```

```http
PATCH /api/v1/applications/{application_id}/form
Content-Type: application/json

{
  "data": { "applicant_name": "合成演示申请人", "contact_phone": "00000000000" },
  "version": 1
}
```

列表、详情与时间线：

```http
GET /api/v1/applications
GET /api/v1/applications/{application_id}
GET /api/v1/applications/{application_id}/timeline
```

### 上传与授权下载材料

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/applications/<application_id>/materials" `
  -H "Authorization: Bearer <token>" `
  -F "requirement_code=ss-1" `
  -F "synthetic_data_confirmed=true" `
  -F "file=@<synthetic.pdf>;type=application/pdf"
```

只接受文件签名与声明一致的 PDF/JPEG/PNG，单文件最大 10 MB。响应包含 `application_version`、哈希和 `NOT_SCANNED_DEMO`，但没有公共下载 URL。

```http
GET /api/v1/applications/{application_id}/materials/{material_id}
```

下载会重新验证对象大小和 SHA-256，并返回 `Cache-Control: private, no-store`。

### 提交、补正、撤回和丢弃

```http
POST /api/v1/applications/{application_id}/submit
Idempotency-Key: <uuid>
Content-Type: application/json

{ "version": 3 }
```

提交前服务端再次检查表单、资格、材料、必要预约和必要核验；不完整返回 422 和结构化 `detail`。

```http
POST /api/v1/applications/{application_id}/supplement
{ "data": { "...": "..." }, "version": 5 }

POST /api/v1/applications/{application_id}/withdraw
Idempotency-Key: <uuid>
{ "version": 4, "comment": "合成演示撤回原因" }

POST /api/v1/applications/{application_id}/discard
Idempotency-Key: <uuid>
{ "version": 1 }
```

## 预约与本地模拟能力

### 预约

```http
POST /api/v1/appointments
Authorization: Bearer <citizen_token>
Idempotency-Key: <uuid>
Content-Type: application/json

{
  "service_id": "<service_uuid>",
  "window_id": "<window_uuid_from_service_windows>",
  "slot_start": "2030-01-02T01:30:00Z"
}
```

```http
GET  /api/v1/appointments
POST /api/v1/appointments/{appointment_id}/cancel
Idempotency-Key: <uuid>
```

同一账号/窗口/时段冲突返回 409。

所属部门工作人员或管理员可登记到场结果：

```http
POST /api/v1/appointments/{appointment_id}/status
Authorization: Bearer <staff_or_admin_token>
Idempotency-Key: <uuid>
Content-Type: application/json

{ "status": "COMPLETED" }
```

`status` 只能为 `COMPLETED/NO_SHOW`；跨部门、已取消或已终结预约不会被推进。

### 模拟身份核验

```http
POST /api/v1/verifications
Idempotency-Key: <uuid>

{ "application_id": "<application_uuid>" }
```

```http
POST /api/v1/verifications/{verification_id}/complete
Idempotency-Key: <uuid>

{ "outcome": "pass" }
```

`outcome` 可为 `pass/fail`；接口只推进状态，不接收照片、视频或生物模板。

### 模拟缴费

```http
POST /api/v1/payments
Idempotency-Key: <uuid>

{ "application_id": "<application_uuid>" }
```

```http
POST /api/v1/payments/{payment_id}/pay
Idempotency-Key: <uuid>

{ "outcome": "failure" }
```

失败订单可用新幂等键和 `{ "outcome": "success" }` 重试。任何 `provider_reference` 都只是本地模拟标识。

群众可在订单成功前取消自己的模拟缴费，无请求体：

```http
POST /api/v1/payments/{payment_id}/cancel
Authorization: Bearer <citizen_token>
Idempotency-Key: <uuid>
```

`CREATED/PENDING/FAILED → CANCELLED` 合法；`SUCCEEDED/CANCELLED` 是终态，重复进行其他状态变更返回 409（相同幂等请求重放原结果除外）。

### 模拟邮寄

```http
POST /api/v1/applications/{application_id}/delivery
Idempotency-Key: <uuid>

{ "recipient": "合成收件人", "address": "演示地址 100 号" }
```

收件信息在持久化前脱敏；不会创建真实快递订单。只有事项详情中的 `mail_supported=true` 才能创建邮寄单；例如企业社保、劳动合同和公积金演示事项仅支持 `DIGITAL_RESULT`，请求邮寄会返回 409。

所属部门工作人员或管理员按顺序推进本地邮寄状态：

```http
POST /api/v1/deliveries/{delivery_id}/status
Authorization: Bearer <staff_or_admin_token>
Idempotency-Key: <uuid>
Content-Type: application/json

{ "status": "DISPATCHED" }
```

再次调用时可使用 `{ "status": "DELIVERED" }`；不能越过状态或处理其他部门办件的邮寄单。

办件申请人可在模拟邮寄发出前取消，无请求体：

```http
POST /api/v1/deliveries/{delivery_id}/cancel
Authorization: Bearer <citizen_token>
Idempotency-Key: <uuid>
```

当前创建结果直接进入 `ACCEPTED`；只有 `ACCEPTED → CANCELLED` 可由群众执行，`DISPATCHED/DELIVERED/CANCELLED` 不能再取消。

## 咨询历史与转人工

登录后发起一次 `/chat`，其 `session_id` 会关联当前账号，随后可调用：

```http
GET  /api/v1/consultations
POST /api/v1/consultations/feedback

{ "session_id": "<session_uuid>", "rating": 5, "comment": "合成演示反馈" }
```

```http
POST /api/v1/consultations/handoffs

{ "session_id": "<session_uuid>", "subject": "需要演示人工解释", "department_id": null }

GET  /api/v1/consultations/handoffs
POST /api/v1/consultations/handoffs/{ticket_id}/messages
GET  /api/v1/consultations/handoffs/{ticket_id}/messages
POST /api/v1/consultations/handoffs/{ticket_id}/cancel
```

消息请求体为 `{ "content": "合成演示消息" }`。取消接口无请求体，但要求群众是工单发起人并提供 `Idempotency-Key`；`QUEUED/CLAIMED/IN_PROGRESS → CANCELLED` 合法，已解决或已取消工单返回 409。

## 工作人员

所有接口需要 `STAFF` token，并限制到工作人员所属部门：

```http
GET  /api/v1/staff/tasks
POST /api/v1/staff/tasks/{task_id}/claim
Idempotency-Key: <uuid>
```

审核决定使用当前办件 `version`：

```http
POST /api/v1/staff/applications/{application_id}/supplement
POST /api/v1/staff/applications/{application_id}/reject
POST /api/v1/staff/applications/{application_id}/approve
POST /api/v1/staff/applications/{application_id}/complete
Idempotency-Key: <uuid>
Content-Type: application/json

{
  "version": 5,
  "comment": "本地演示审核意见",
  "require_payment": false
}
```

人工咨询：

```http
GET  /api/v1/staff/handoffs
POST /api/v1/staff/handoffs/{ticket_id}/messages
POST /api/v1/staff/handoffs/{ticket_id}/resolve
```

未认领、跨部门、版本落后或任务已被其他人认领时不会推进状态。

## 管理员

需要 `ADMIN` token：

```http
GET  /api/v1/admin/departments
POST /api/v1/admin/departments
GET  /api/v1/admin/windows
POST /api/v1/admin/windows
POST /api/v1/admin/staff
GET  /api/v1/admin/accounts
POST /api/v1/admin/accounts/{account_id}/status
GET  /api/v1/admin/services
POST /api/v1/admin/services
POST /api/v1/admin/services/{service_id}/versions
POST /api/v1/admin/services/{service_id}/lifecycle
POST /api/v1/admin/knowledge
POST /api/v1/admin/knowledge/{job_id}/retry
POST /api/v1/admin/knowledge/{job_id}/archive
GET  /api/v1/admin/audit
GET  /api/v1/admin/metrics
```

冻结/解冻：

```json
{ "active": false }
```

生命周期写入要求 `Idempotency-Key`：

```json
{
  "target_status": "PUBLISHED",
  "version_id": "<new_version_uuid>"
}
```

`target_status` 可为 `PUBLISHED`、`SUSPENDED`、`RETIRED`；终止后不可恢复。

知识上传使用 multipart，接受 PDF/DOCX/TXT/Markdown：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/admin/knowledge" `
  -H "Authorization: Bearer <admin_token>" `
  -F "title=演示知识" `
  -F "source=demo://admin-upload" `
  -F "file=@<synthetic.md>;type=text/markdown"
```

成功上传响应直接提供 `job_id`。若首次索引或发布失败，结构化 409 的 `error.detail.job_id` 提供同一标识；API 当前没有独立的知识任务列表端点，客户端应保存该标识，也可通过审计事件追踪操作。

`INDEX_FAILED` 任务可重试，无请求体：

```http
POST /api/v1/admin/knowledge/{job_id}/retry
Authorization: Bearer <admin_token>
Idempotency-Key: <uuid>
```

只有 `ACTIVE/SUPERSEDED` 任务可归档，无请求体：

```http
POST /api/v1/admin/knowledge/{job_id}/archive
Authorization: Bearer <admin_token>
Idempotency-Key: <uuid>
```

归档保留 PostgreSQL 文档、任务和不可变审计；若该文档没有其他 ACTIVE 任务，其知识块会标记 `ARCHIVED` 并从 Milvus 检索集合移除。重试成功、归档成功都会使公开 Redis 检索缓存失效，下一次公开咨询重新取证。

## 完整 OpenAPI 操作清单

以下 76 个 method/path 与当前最终 `/openapi.json` 一致；版本化团队 RAG 通过运维命令导入，不暴露额外业务路由。请求体、认证和状态规则以上文及实时 OpenAPI 为准。

```text
GET /health/live
GET /health/ready
POST /api/v1/auth/request-code
POST /api/v1/auth/register
POST /api/v1/auth/login
POST /api/v1/auth/refresh
POST /api/v1/auth/logout
GET /api/v1/auth/me
GET /api/v1/services
GET /api/v1/services/{service_id}
POST /api/v1/services/{service_id}/eligibility
GET /api/v1/services/{service_id}/materials
POST /api/v1/services/{service_id}/materials/evaluate
GET /api/v1/services/{service_id}/process
GET /api/v1/services/{service_id}/form
GET /api/v1/services/{service_id}/windows
POST /api/v1/chat
POST /api/v1/chat/stream
POST /api/v1/applications
GET /api/v1/applications
GET /api/v1/applications/{application_id}
PATCH /api/v1/applications/{application_id}/form
POST /api/v1/applications/{application_id}/materials
GET /api/v1/applications/{application_id}/materials/{material_id}
POST /api/v1/applications/{application_id}/submit
POST /api/v1/applications/{application_id}/supplement
POST /api/v1/applications/{application_id}/withdraw
POST /api/v1/applications/{application_id}/discard
GET /api/v1/applications/{application_id}/timeline
POST /api/v1/applications/{application_id}/delivery
GET /api/v1/consultations
POST /api/v1/consultations/feedback
POST /api/v1/consultations/handoffs
GET /api/v1/consultations/handoffs
POST /api/v1/consultations/handoffs/{ticket_id}/messages
GET /api/v1/consultations/handoffs/{ticket_id}/messages
POST /api/v1/consultations/handoffs/{ticket_id}/cancel
GET /api/v1/staff/tasks
POST /api/v1/staff/tasks/{task_id}/claim
POST /api/v1/staff/applications/{application_id}/supplement
POST /api/v1/staff/applications/{application_id}/reject
POST /api/v1/staff/applications/{application_id}/approve
POST /api/v1/staff/applications/{application_id}/complete
GET /api/v1/staff/handoffs
POST /api/v1/staff/handoffs/{ticket_id}/messages
POST /api/v1/staff/handoffs/{ticket_id}/resolve
GET /api/v1/admin/departments
POST /api/v1/admin/departments
GET /api/v1/admin/windows
POST /api/v1/admin/windows
POST /api/v1/admin/staff
GET /api/v1/admin/accounts
POST /api/v1/admin/accounts/{account_id}/status
GET /api/v1/admin/services
POST /api/v1/admin/services
POST /api/v1/admin/services/{service_id}/versions
POST /api/v1/admin/services/{service_id}/lifecycle
POST /api/v1/admin/knowledge
POST /api/v1/admin/knowledge/{job_id}/retry
POST /api/v1/admin/knowledge/{job_id}/archive
GET /api/v1/admin/audit
GET /api/v1/admin/metrics
GET /api/v1/appointments
POST /api/v1/appointments
POST /api/v1/appointments/{appointment_id}/cancel
POST /api/v1/appointments/{appointment_id}/status
POST /api/v1/payments
POST /api/v1/payments/{payment_id}/pay
POST /api/v1/payments/{payment_id}/cancel
POST /api/v1/verifications
POST /api/v1/verifications/{verification_id}/complete
POST /api/v1/deliveries/{delivery_id}/status
POST /api/v1/deliveries/{delivery_id}/cancel
POST /api/v1/integrations/metastudio/client-sessions
POST /api/v1/integrations/metastudio/llm
POST /api/v1/integrations/metastudio/action-intents/{intent_id}/exchange
```

## 可选 MetaStudio 智能交互

MetaStudio 默认关闭；关闭或服务端 SDK/IAM/robot 配置不完整时，创建客户端会话返回结构化 503，且不会外呼华为云。启用后 Android 原生网关发送空 JSON：

```http
POST /api/v1/integrations/metastudio/client-sessions
Content-Type: application/json

{}
```

响应中的 `once_code` 是短期敏感值，只能在内存中交给本地 SDK 包装页，不写日志、磁盘或 WebView URL。`server_address` 必须是固定北京四白名单地址，robotId 由后端配置提供，三者都不能由 WebView 自定义。

MetaStudio 唯一回调路径同时支持普通响应和 SSE。以下仅展示请求体结构；真实请求的 MSS_A `secret/time_stamp` query 由 MetaStudio 生成，不应复制到文档、命令、日志或工单：

```json
{
  "messages": [{"content": "如何办理演示社保卡"}],
  "app_id": "由服务端校验的应用标识",
  "user": "供应方会话用户标识",
  "session_id": "供应方会话标识",
  "is_stream": true,
  "extend_param": {"client_id": "合成演示客户端"}
}
```

回调边界先验证 HMAC、时间窗与重放，再进入咨询协调者；鉴权失败固定为 400，不能调用 LLM/RAG 或产生动作。数字人建议的政务动作只返回短期 intent，登录客户端还需用 Bearer 交换：

```http
POST /api/v1/integrations/metastudio/action-intents/{intent_id}/exchange
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "chat_id": "供应方会话内消息标识"
}
```

交换响应只是需要用户确认的受控动作封包，不能绕过目标业务接口自身的角色、所有权、幂等、版本和状态机校验。完整部署与隐私边界见 [MetaStudio 接入说明](metastudio-integration.md)。

## 统一错误

业务错误统一封装：

```json
{
  "error": {
    "code": "optimistic_lock_conflict",
    "message": "办件版本或状态已变化，请刷新后重试",
    "request_id": null,
    "detail": null
  }
}
```

| HTTP | 语义 |
| --- | --- |
| 401 | 未登录、令牌无效/过期/冻结失效 |
| 403 | 越权、跨用户或跨部门 |
| 404 | 资源不存在 |
| 409 | 版本、状态、预约、幂等或并发认领冲突 |
| 422 | 请求、表单、材料、资格或文件不完整 |
| 502 | DeepSeek 调用失败，禁止伪造回答 |
| 503 | PostgreSQL 或全栈核心依赖不可用 |
