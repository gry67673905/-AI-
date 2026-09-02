# docs(chat): 记录多轮咨询与 SSE 实现

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

## 会话模型

说明匿名会话、登录用户所有权、最近八条脱敏历史和新对话行为。

## 咨询编排

记录事项匹配、公共检索、GroundedAnswerPolicy、模型调用和消息持久化顺序。

## 流式协议

定义 meta、delta、done、error 事件及受控 ui_cards 的作用。
