# 管理员命令与 API 追踪矩阵

> 课程验收补录 / retrospective evidence：内容依据仓库在 GitHub 实际创建时的代码、接口、文档与测试整理；它不倒填历史日期、不伪造原开发过程，完成与未完成状态均按证据如实标注。

## 证据边界

本文件针对“管理员端”整理当前仓库可核查事实；它不是原开发日期的伪造记录。

### 关联路径

- `android/app/src/main/assets/index.html`
- `android/app/src/main/assets/portal-app-v2.js`
- `android/app/src/main/java/com/example/aicompanion/portal/coordinator/AdminCoordinator.java`
- `android/app/src/main/java/com/example/aicompanion/portal/gateway/OkHttpAdminGateway.java`
- `backend/app/application/coordinators.py`
- `backend/app/boundaries/http.py`

### 关联接口或符号

- `GET|POST /api/v1/admin/departments`
- `GET|POST /api/v1/admin/windows`
- `POST /api/v1/admin/staff`
- `GET /api/v1/admin/accounts`
- `GET|POST /api/v1/admin/services`
- `GET /api/v1/admin/audit`
- `GET /api/v1/admin/metrics`
- `section-admin_overview`
- `section-admin_catalog`
- `AdminCoordinator`

## 客户端命令

本地门户产生受控管理员命令，`AdminCoordinator` 和 `OkHttpAdminGateway` 将其映射到固定管理接口。

## 服务端协调

`AdminConsoleBoundary` 只负责 HTTP 边界，组织、事项、知识和审计规则由对应协调器与仓储执行。

## 审计与限制

文档标注每项高权限操作的角色、版本、幂等和审计要求，并明确 UI 不持有云密钥或数据库连接。
