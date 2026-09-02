# 工作人员端当前实现说明

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

## 补录说明

本文依据冻结 main 的工作人员 SPA 分区、协调器和服务端路由整理，作为课程验收证据而非原始需求时间线。

## 待办审核

工作人员可读取所属范围待办、认领任务，并以版本和幂等键执行补正、驳回、批准或完成；服务端负责最终状态校验。

## 人工咨询

工作台另行展示人工咨询工单，支持消息回复和结单；该流程与办件审核分离，避免把咨询文本当作审批决定。
