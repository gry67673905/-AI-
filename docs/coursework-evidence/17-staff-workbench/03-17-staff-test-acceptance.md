# 工作人员测试与演示验收报告

> 课程验收补录 / retrospective evidence：内容依据仓库在 GitHub 实际创建时的代码、接口、文档与测试整理；它不倒填历史日期、不伪造原开发过程，完成与未完成状态均按证据如实标注。

## 证据边界

本文件针对“工作人员端”整理当前仓库可核查事实；它不是原开发日期的伪造记录。

### 关联路径

- `android/app/src/main/assets/index.html`
- `android/app/src/main/assets/portal-app-v2.js`
- `android/app/src/main/java/com/example/aicompanion/portal/coordinator/StaffTaskCoordinator.java`
- `android/app/src/main/java/com/example/aicompanion/portal/gateway/OkHttpStaffGateway.java`
- `backend/app/boundaries/http.py`
- `android/app/src/test/java/com/example/aicompanion/portal/coordinator/PortalCoordinatorViewModelTest.java`

### 关联接口或符号

- `GET /api/v1/staff/tasks`
- `POST /api/v1/staff/tasks/{task_id}/claim`
- `POST /api/v1/staff/applications/{application_id}/supplement|reject|approve|complete`
- `GET /api/v1/staff/handoffs`
- `section-staff_tasks`
- `section-staff_handoffs`
- `StaffTaskCoordinator`

## 功能验收

验收覆盖任务筛选、认领、材料检查、四类审核结果、咨询回复与结单，并验证页面在刷新后反映服务器状态。

## 权限验收

群众、管理员、跨部门工作人员和未认领工作人员的越权请求必须被拒绝，不能只依赖隐藏按钮。

## 并发验收

重复幂等请求返回一致结果，旧版本操作产生可理解的冲突，客户端重新加载而不覆盖他人已完成决定。
