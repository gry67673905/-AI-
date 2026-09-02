# 群众端测试与演示验收报告

> 课程验收补录 / retrospective evidence：内容依据仓库在 GitHub 实际创建时的代码、接口、文档与测试整理；它不倒填历史日期、不伪造原开发过程，完成与未完成状态均按证据如实标注。

## 证据边界

本文件针对“群众端体验”整理当前仓库可核查事实；它不是原开发日期的伪造记录。

### 关联路径

- `android/app/src/main/assets/index.html`
- `android/app/src/main/assets/portal-app-v2.js`
- `android/app/src/main/java/com/example/aicompanion/portal/coordinator/CitizenCoordinator.java`
- `android/app/src/main/java/com/example/aicompanion/portal/coordinator/PortalCoordinatorViewModel.java`
- `android/app/src/main/java/com/example/aicompanion/portal/model/PortalContract.java`

### 关联接口或符号

- `CitizenCoordinator`
- `PortalCoordinatorViewModel`
- `PortalContract.Command`
- `section-consultation`
- `section-services`
- `section-applications`
- `GET /api/v1/services`
- `POST /api/v1/applications`

## 核心旅程

验收覆盖演示注册/登录、事项查找、草稿填写、预审、材料、提交、进度、AI 对话和退出。

## 异常旅程

会话失效、网络失败、SSE 中断、材料失败和文件校验错误均需保留可理解状态，并阻止重复或未确认写入。

## 展示约束

演示账号、合成材料和 DEMO 网点必须持续标注；补录不把模拟数据描述为真实政务办理结果。
