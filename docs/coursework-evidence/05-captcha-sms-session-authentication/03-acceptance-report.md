# docs(auth): 补录会话认证负向与隐私验收

> 课程验收补录 / retrospective evidence：内容依据仓库在 GitHub 实际创建时的代码、接口、文档与测试整理；它不倒填历史日期、不伪造原开发过程，完成与未完成状态均按证据如实标注。

## 证据边界

本文件针对“Captcha、短信与会话认证”整理当前仓库可核查事实；它不是原开发日期的伪造记录。

### 关联路径

- `backend/app/security.py`
- `backend/app/application/coordinators.py`
- `backend/migrations/versions/0002_identity_catalog.py`
- `android/app/src/main/java/com/example/aicompanion/portal/coordinator/AuthCoordinator.java`
- `backend/tests/test_security.py`

### 关联接口或符号

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `AuthCoordinator`
- `AndroidKeystoreSessionStore`

## 负向场景

记录错误凭据、无效或撤销 refresh、账号冻结、角色越权和过期令牌。

## 隐私检查

确认 API、日志和测试输出不包含密码、JWT、refresh 哈希或本地演示凭据。

## 真实验收边界

明确冻结 main 没有真实短信与 Captcha 实现，不能把后续本地工作或人工测试冒充为该快照证据。
