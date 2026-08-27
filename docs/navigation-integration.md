# 华为 Navi Kit 政务网点导航（云端真机候选）

## 当前边界

本阶段固定使用华为 Navi Kit `6.13.0.300`、Map Kit、Location Kit 和现有 AG Connect 配置，支持步行/驾车路线预览及应用内逐向语音提示。网点均为单城市合成演示数据，页面必须显示“演示路线，不用于实际出行”。代码、Mock 测试和 debug APK 可在本地生成，但在 Android 真机完成算路、语音、偏航重算和权限验收前不得作为发布版本。

WebView、数字人和模型只能提交事项 UUID。它们不能提交坐标、网点、URL、包名或任意 Intent。原生页会重新读取已发布事项的活动网点，用户选择网点和出行方式后才可规划路线；路线成功前“开始导航”保持禁用。

## 公共目录接口

```http
GET /api/v1/services/{service_id}/navigation-options
```

接口无需登录，也不接收用户位置。响应包含事项的 `handling_mode`、`online_status`、状态原因，以及按目录优先级排列的活动网点。网点坐标固定为 `GCJ02`，并逐项标记 `DEMO` 或 `VERIFIED`。只要返回集合中仍含 `DEMO` 网点，客户端就继续显示演示提示。

数据库迁移 `0007_navigation_catalog` 新增事项—网点多对多关系，并将旧 `government_services.window_id` 以优先级 `0` 回填；旧字段暂留一版兼容。公开读取同时过滤未发布事项、停用关联和停用网点。

## CSV 管理

模板与演示样例位于：

- `backend/fixtures/navigation_catalog_template.csv`
- `backend/fixtures/navigation_catalog_demo.csv`
- `backend/fixtures/navigation_catalog_chengdu_device_test.csv`

真机候选只导入成都合成数据：事项 `DEMO-ID-REISSUE-001` 与 `DEMO-HOUSING-FUND-001` 各关联三个独立 DEMO 网点，坐标系固定 `GCJ02`、`city_code=510100`、优先级 `0/10/20`。这些坐标和地址仅用于 SDK 算路测试，任何页面都必须继续显示“演示路线，不用于实际出行”。

管理员先执行预校验，再执行真实导入：

```http
POST /api/v1/admin/navigation-catalog/import?dry_run=true
Content-Type: multipart/form-data

file=<UTF-8 CSV>
```

确认报告无错误后把 `dry_run` 改为 `false`。文件上限为 1 MiB、1000 行；固定 15 列，支持模板中的中文表头及对应英文别名。真实导入在一个数据库事务内完成，任一行失败都会整体回滚。CSV 对其中出现的每个事项是全量快照：未再列出的旧关联会被停用，仍被其他事项引用的网点记录不会被全局停用；旧 `window_id` 兼容字段改指向本次优先级最高的活动网点。`VERIFIED` 行必须提供来源和带时区的 ISO-8601 核验时间。

## Android 流程与隐私

1. 门户或数字人确认卡只调用 `openServiceNavigation(service_id)`。
2. 非导出的原生导航页通过固定 HTTPS 路径重新获取目录，不使用 WebView Token 或目的地参数。
3. 用户点击“启用本页前台定位”后才申请/启动 Location Kit；首次定位 10 秒超时。当前位置只在 Activity 内存中用于最近三个网点排序和 Navi Kit，不上传项目后端、不持久化、不写日志。
4. 用户默认选择步行，也可切换驾车。只有点击“路线预览”时才延迟创建 Navi Kit 实例。
5. 路线成功后以 Map Kit 绘制轨迹，并显示距离和预计耗时；随后才能开始 GPS 导航。Navi 逐向文本由 Activity 内 Android TTS 播报。
6. 页面离开前台即停止定位和导航；销毁时移除 Navi 监听并释放 Navi、地图及 TTS。失败时保留网点和标点，只提供固定事项 ID 的重试，不跳转外部地图。

MetaStudio 隔离 WebView 仍只允许麦克风权限，不获得定位、地图或 Navi 权限。数字人 `OPEN_SERVICE_NAVIGATION` 交换结果严格只含 `prefill.service_id`，回到门户显示确认卡；用户确认后才进入原生页。匿名用户也可交换这一公共只读意图，其他业务意图仍要求登录。

## 本地验收

自动化只使用 Fake Navi/Location、MockWebServer 和后端 Mock，不会调用真实路线服务：

```powershell
Set-Location .\android
D:\AndroidDev\gradle-8.14.5\bin\gradle.bat :app:testDebugUnitTest :app:lintDebug :app:assembleDebug
```

后续真机硬门禁包括：步行/驾车算路、路线预览、逐向语音、偏航重算、定位拒绝/超时、匿名数字人确认跳转，以及离开页面后的资源释放。未完成这些项目时 APK 仅标记为本地 PoC。
