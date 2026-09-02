# 工作人员接口与权限追踪矩阵

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

## 页面到网关

本地门户只派发白名单工作人员命令，`StaffTaskCoordinator` 校验命令并调用 `OkHttpStaffGateway` 的固定路径。

## 服务端决策

`StaffWorkbenchBoundary` 将请求交给审核或咨询协调器，角色、部门、版本、任务归属和幂等键由服务端验证。

## 审计边界

任务认领和审核决策应留下可追踪的结果审计，但不把完整材料、群众敏感字段、评论正文或访问令牌复制到普通日志。
