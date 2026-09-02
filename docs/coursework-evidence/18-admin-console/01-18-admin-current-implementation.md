# 管理员端当前实现说明

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

## 补录说明

本文只记录冻结 main 后端实际支持并已接入本地 SPA 的管理员能力，不将 Compose 或设想页面描述为已实现。

## 管理能力

控制台覆盖指标、组织窗口、账号工作人员、事项版本生命周期、知识资料和审计；该快照没有政务消息来源状态。

## 写入边界

所有写入由固定网关发送类型化载荷，服务端再次执行 ADMIN 角色、字段、版本和幂等校验。
