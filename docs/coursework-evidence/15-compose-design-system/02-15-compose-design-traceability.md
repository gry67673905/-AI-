# CSS 到 Compose 的拟议追踪矩阵

> 课程验收补录 / retrospective evidence：内容依据仓库在 GitHub 实际创建时的代码、接口、文档与测试整理；它不倒填历史日期、不伪造原开发过程，完成与未完成状态均按证据如实标注。

## 证据边界

本文件针对“Compose 设计系统”整理当前仓库可核查事实；它不是原开发日期的伪造记录。

### 关联路径

- `android/app/src/main/assets/index.html`
- `android/app/src/main/assets/style.css`
- `android/app/src/main/assets/portal-app-v2.js`
- `android/app/src/main/java/com/example/aicompanion/MainActivity.java`
- `android/app/src/main/java/com/example/aicompanion/portal/boundary/SecureWebViewHost.java`

### 关联接口或符号

- `MainActivity`
- `SecureWebViewHost`
- `PortalJsBoundary`
- `SecureAssetWebViewClient.START_URL`
- workspace[data-section]

## 视觉来源

当前样式由冻结 main 的 CSS 和本地资产提供；拟议迁移可沿用其颜色、背景、卡片和圆角，但不得声称 Compose 已存在。

## 组件映射

文档把现有 card、section-heading、状态和消息类映射到未来群众、工作人员、管理员 Compose 组件。

## 架构边界

拟议组件只接收展示模型和类型化回调；网络、会话、外部 Activity 与安全下载应继续由控制器和原生边界处理。
