# docs(security): 建立授权与审计追踪矩阵

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

## 角色矩阵

选择群众、工作人员和管理员代表接口，标记其角色及资源级条件。

## 事务保护

将 Idempotency-Key、payload hash、version 和状态转换映射到协调者与 repository。

## 审计结果

说明关键写入如何记录 actor、资源和结果，同时避免保存敏感正文。
