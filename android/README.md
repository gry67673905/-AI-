# Android 客户端骨架

该模块保留 `com.example.aicompanion`、AG Connect/HMS Core 检测、独立事项导航页和办件材料 DOCX
保存边界。主页面由本地 `WebViewAssetLoader` 提供，WebView 不能访问网络；全部 API、Token 和二进制
下载只经过原生强类型网关。

## 构建与测试

1. 将 `local.properties.example` 复制为 `local.properties` 并填写 Android SDK 路径。
2. 如需 HMS 地图能力，在 `app/agconnect-services.json` 放置本机 AG Connect 配置。该文件已忽略提交。
3. 执行 `./gradlew testDebugUnitTest assembleDebug`（Windows 使用 `gradlew.bat`）。

当前 APK 版本名为 `0.3.0-material-docgen-test`。它仍是联调候选：构建和 JVM 测试本身不会调用真实
路线或模型、启动模拟器或授权上线。

Debug 默认后端为当前云端 HTTPS 入口 `https://123.249.68.176`。可以在构建时显式覆盖，例如：

```powershell
.\gradlew.bat assembleDebug -PgovApiBase=https://123.249.68.176
```

仅在明确希望执行真实只读请求时运行可选云端测试：

```powershell
.\gradlew.bat testDebugUnitTest `
  -DliveBackendTest=true `
  -DliveBackendUrl=https://123.249.68.176
```

MetaStudio 数字人使用独立 `:digital_human` 进程和隔离 WebView；不会放宽群众门户 WebView，也不会把
JWT、华为 AK/SK 或 APPKEY 注入页面。发布前必须按
[`docs/metastudio-integration.md`](../docs/metastudio-integration.md) 在 Android 10 与 Android 12+
真机完成 System WebView、WebRTC、麦克风、SIS、流式回答和 `extendParam` PoC。PoC 未通过时可以生成
调试候选 APK，但不得发布数字人版本。

包装页启用 Web SDK 自带的覆盖式流式 ASR 字幕，并使用 `speechRecognized` 只向原生层发送
`asr_partial`/`asr_final` 固定状态；`speechRecognized` 的原始文字及其 `chatId`/`resultId` 不会跨越
WebView 消息桥。MetaStudio 最终形成的完整问题才进入既有 LLM 回调；最终
`semanticRecognized` 中经校验的不透明语义 `chatId` 会与 `intent_id` 一起进入原生层和意图交换接口，
但不含 ASR 原文。SDK 显式保持会话内持续拾音并允许 VAD 人声打断，但仍要求用户首次点击开始和授予
麦克风权限；休眠、会话结束或离开 Activity 后会禁用迟到的识别事件，离开 Activity 会销毁拾音任务。

登录用户可在数字人页手动开启独立 CameraX 视觉辅助。摄像头默认关闭，只使用 `Preview` 与
`ImageAnalysis`，不启用录像或录音。首个 ASR partial 到 final 期间以不超过 2 FPS 持续筛选候选帧，
并保留约 1 秒的纯内存前置缓存以覆盖只有 final 的短句；每轮最多发送 7 张普通帧和 1 张保留末帧，
单张重编码 JPEG 不超过约 96 KiB。短期视觉票据只存在原生内存和 `Authorization` 请求头，不进入 WebView、URL 或
日志；断线、离开页面和关闭开关都会立即释放相机、队列及票据。当前本地配置固定使用无外呼的
`VISION_PROVIDER=mock`，详情见 [`docs/metastudio-integration.md`](../docs/metastudio-integration.md)。

门户的“原生路线导航”和数字人 `OPEN_SERVICE_NAVIGATION` 建议都只向非导出的原生页面传递
`service_id`。原生页再匿名读取固定的 `/api/v1/services/{service_id}/navigation-options`，在本机按
GCJ02 位置选择最近三个活动网点；当前位置不会发给项目后端或任一 WebView。定位须由用户在该页
显式开启；网点距离排序只取一次定位 fix，取得后立即移除 Location Kit 更新。只有路线预览完成且用户
点击“开始导航”后，才在该页前台启动连续定位以支持逐向导航；停止导航或离开页面都会立即释放定位。
默认步行，可切换驾车；路线预览与开始导航是两个独立确认步骤。DEMO 网点始终显示提示，当前 PoC
不调用真实路线。

群众工作台继续可通过办件 UUID 加载可生成材料模板；普通 AI 咨询也可展示模板卡，经登录用户显式确认后生成不绑定办件的空白模板。两种模式后台生成完成后都只把 `generation_id` 交给原生
`MaterialDocumentSaveBoundary`。原生网关固定请求鉴权下载路径，拒绝重定向，并校验 DOCX MIME、
10 MiB 上限、SHA-256、OOXML 必需部件、压缩展开上限、宏、嵌入对象、`altChunk` 和外部关系。通过后
使用 Android SAF `CreateDocument` 让用户选择保存位置并尝试用 WPS/Word 打开；WebView 不能提供 URL、
路径或任意 Intent。详见 [`docs/material-document-generation.md`](../docs/material-document-generation.md)。

该模块不包含模拟器启动、APK 安装或手机端视觉回归步骤。
