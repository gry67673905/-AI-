# Android 客户端骨架

该模块保留 `com.example.aicompanion`、AG Connect/HMS Core 检测和最小 HMS 地图页。主页面由本地
`WebViewAssetLoader` 提供，WebView 不能访问网络；聊天请求只经原生 `GovAssistantRepository` 调用
`POST /api/v1/chat`。

## 构建与测试

1. 将 `local.properties.example` 复制为 `local.properties` 并填写 Android SDK 路径。
2. 如需 HMS 地图能力，在 `app/agconnect-services.json` 放置本机 AG Connect 配置。该文件已忽略提交。
3. 执行 `./gradlew testDebugUnitTest assembleDebug`（Windows 使用 `gradlew.bat`）。

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

该模块不包含模拟器启动、APK 安装或手机端视觉回归步骤。
