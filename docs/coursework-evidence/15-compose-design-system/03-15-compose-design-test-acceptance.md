# Compose 视觉测试与验收计划

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

## 结构断言

计划中的测试应检查 Compose Host、真实 Icon、无文字假图标的底部导航和品牌资源；冻结 main 尚无这些测试。

## 状态测试

计划用 Fake controller 为三角色提供加载、空、错误和正常状态，在不依赖云端时验证组件组合。

## 视觉限制

未来截图与真机需覆盖系统字体、状态栏和设备密度；本文不把计划或源码结构断言伪装成最终像素验收。
