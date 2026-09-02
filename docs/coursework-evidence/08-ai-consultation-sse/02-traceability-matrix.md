# docs(chat): 建立咨询请求与卡片追踪矩阵

> 课程验收补录 / retrospective evidence：内容依据仓库在 GitHub 实际创建时的代码、接口、文档与测试整理；它不倒填历史日期、不伪造原开发过程，完成与未完成状态均按证据如实标注。

## 证据边界

本文件针对“AI 咨询与 SSE”整理当前仓库可核查事实；它不是原开发日期的伪造记录。

### 关联路径

- `backend/app/application/coordinators.py`
- `backend/app/boundaries/http.py`
- `backend/app/boundaries/chat_mapping.py`
- `backend/tests/test_api.py`
- `backend/tests/test_consultation_material_documents.py`

### 关联接口或符号

- `ConsultationCoordinator`
- `GroundedAnswerPolicy`
- `POST /api/v1/chat`
- `POST /api/v1/chat/stream`
- `GET /api/v1/consultations`
- `GET /api/v1/consultations/{session_id}/messages`

## 输入映射

把 ChatRequest 映射到 ChatCommand，并标记 session、service 和 application 的权限约束。

## 结果映射

说明协调者结果如何转换为 JSON 响应或 SSE 元数据、增量和完成事件。

## UI 安全

记录模型不能决定资源 ID，卡片不含 URL、令牌、对象键或任意 HTML。
