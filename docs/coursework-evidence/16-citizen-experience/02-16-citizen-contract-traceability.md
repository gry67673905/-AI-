# 群众端页面与 API 追踪矩阵

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

## 状态与动作

页面通过白名单桥接命令表达查询、提交、重试或启动原生能力；协调器验证命令并持有网关，WebView 不接触 Token。

## 业务接口

事项搜索与详情、申请创建与表单、材料任务和咨询历史映射到固定 `/api/v1` 路径；政务消息不属于冻结 main。

## 原生动作

数字人、Navi、文档选择与保存及普通语音由窄边界执行，参数使用可信 ID；该快照无 Captcha Activity 或新闻原文命令。
