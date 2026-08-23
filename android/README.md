# Android 客户端骨架

该模块保留 `com.example.aicompanion`、AG Connect/HMS Core 检测和最小 HMS 地图页。主页面由本地
`WebViewAssetLoader` 提供，WebView 不能访问网络；聊天请求只经原生 `GovAssistantRepository` 调用
`POST /api/v1/chat`。

## 构建与测试

1. 将 `local.properties.example` 复制为 `local.properties` 并填写 Android SDK 路径。
2. 如需 HMS 地图能力，在 `app/agconnect-services.json` 放置本机 AG Connect 配置。该文件已忽略提交。
3. 执行 `./gradlew testDebugUnitTest assembleDebug`（Windows 使用 `gradlew.bat`）。

Debug 默认后端为 `http://10.0.2.2:8000`。可以在构建时覆盖，例如：

```powershell
.\gradlew.bat assembleDebug -PgovApiBase=https://123.249.68.176
```

仅在本地全栈已启动且明确希望执行真实请求时运行可选测试：

```powershell
.\gradlew.bat testDebugUnitTest `
  -DliveBackendTest=true `
  -DliveBackendUrl=http://127.0.0.1:8000
```

该模块不包含模拟器启动、APK 安装或手机端视觉回归步骤。
