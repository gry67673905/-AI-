# docs(security): 记录 RBAC 与资源级授权实现

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

## 身份与角色

说明 Principal、群众、工作人员和管理员角色，以及 access token 验证入口。

## 资源授权

记录群众所有权、工作人员部门/认领和管理员边界，强调 role 不是唯一判断。

## 写入保护

概括幂等键、乐观锁、领域状态机和追加式审计的组合约束。
