# WebView 视觉基线与 Compose 缺口说明

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

## 补录说明

本文记录冻结 main 的本地 WebView 视觉基础与 Compose 缺口，是课程证据整理，不修改原始设计团队或代码作者归属。

## 现有视觉资产

`style.css`、`index.html` 与 `portal-app-v2.js` 管理当前页面样式、分区和交互；冻结 main 未包含 Compose 主题或产品组件。

## 安全宿主

`MainActivity` 与 `SecureWebViewHost` 只加载受信任本地资产，后续 Compose 迁移仍需保留同等原生安全边界。
