# docs(security): 补录越权与重放安全验收

> 课程验收补录 / retrospective evidence：内容依据仓库在 GitHub 实际创建时的代码、接口、文档与测试整理；它不倒填历史日期、不伪造原开发过程，完成与未完成状态均按证据如实标注。

## 证据边界

本文件针对“RBAC、审计与安全”整理当前仓库可核查事实；它不是原开发日期的伪造记录。

### 关联路径

- `backend/app/security.py`
- `backend/app/domain/policies.py`
- `docs/role-permissions.md`
- `backend/tests/test_security.py`

### 关联接口或符号

- `Principal`
- `Role.CITIZEN`
- `Role.STAFF`
- `Role.ADMIN`
- `AuthorizedCaseQueryService`
- `IdempotencyCoordinator`

## 越权检查

记录跨用户、跨部门、未认领任务和错误角色访问的拒绝证据。

## 会话与重放

记录旧 token、冻结账号、并发相同幂等键和相同键不同载荷场景。

## 声明限制

明确该验收是代码与自动化证据，不等同于第三方渗透或合规认证。
