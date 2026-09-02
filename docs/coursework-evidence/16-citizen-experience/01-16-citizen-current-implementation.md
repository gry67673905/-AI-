# 群众端 SPA 当前实现与关键旅程说明

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

## 补录说明

本文以冻结 main 的本地 SPA、协调器和安全 WebView 为准，整理群众端已实现旅程，不补写虚构的开发先后顺序。

## 主要页面

群众端包含演示认证、事项、表单与进度、AI 咨询、数字人入口和个人中心，并固定显示演示服务声明；该快照没有政务消息页面。

## 能力复用

本地 SPA 通过 PortalJsBoundary、PortalCoordinatorViewModel 和类型化网关复用安全会话及原生边界，Token 不进入 WebView。
