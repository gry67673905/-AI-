# 管理员测试与演示验收报告

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

## 功能测试

测试覆盖组织与窗口创建载荷、账号状态、事项版本与生命周期、知识任务、审计和指标读取。

## 权限测试

非管理员的同路径请求必须由服务端拒绝；无效 ID、冲突版本、重复代码和不安全文件也必须失败。

## 演示约束

课程展示使用合成账号与数据，不运行真实生产管理操作，也不在文档中记录密码、令牌或私有知识内容。
