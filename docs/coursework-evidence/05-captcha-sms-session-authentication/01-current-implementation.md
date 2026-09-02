# docs(auth): 记录现有会话认证与供应商接入缺口

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

## 认证组成

解释冻结 main 的演示验证码、用户名密码注册/登录、refresh 轮换和登出，并明确真实 Captcha/短信尚未实现。

## 数据最小化

说明密码哈希、refresh 哈希、token_version 与 Android Keystore 的数据边界。

## 安全失败

记录错误凭据、冻结账号、撤销 refresh 和过期令牌的拒绝策略。
