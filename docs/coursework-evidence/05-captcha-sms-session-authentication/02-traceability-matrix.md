# docs(auth): 建立账号与会话接口追踪

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

## 接口矩阵

列出注册、密码登录、刷新、登出和 me 的授权要求。

## 会话生命周期

说明 access/refresh 用途隔离、有效期、哈希保存、轮换、撤销和账号冻结。

## 提供商映射

把 boundary 和 coordinator 调用映射到 security.py、AuthCoordinator 与 0002 身份数据字段。
