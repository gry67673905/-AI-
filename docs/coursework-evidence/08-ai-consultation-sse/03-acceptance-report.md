# docs(chat): 补录流式咨询与历史隔离验收

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

## 流式验收

记录事件顺序、最终答案一致性、中断清理和结构化配额错误。

## 历史验收

覆盖当前用户恢复、跨用户拒绝、匿名边界、删除会话和并发首消息。

## 隐私验收

说明 PII 在持久化、检索、缓存和模型上下文之前的脱敏断言。
