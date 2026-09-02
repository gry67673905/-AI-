# 导航契约与状态机追踪矩阵

> 课程验收补录 / retrospective evidence：内容依据仓库在 GitHub 实际创建时的代码、接口、文档与测试整理；它不倒填历史日期、不伪造原开发过程，完成与未完成状态均按证据如实标注。

## 证据边界

本文件针对“华为地图与 Navi Kit”整理当前仓库可核查事实；它不是原开发日期的伪造记录。

### 关联路径

- `backend/app/application/navigation.py`
- `backend/migrations/versions/0007_navigation_catalog.py`
- `android/app/src/main/java/com/example/aicompanion/navigation/engine/HuaweiNaviEngineAdapter.java`
- `android/app/src/main/java/com/example/aicompanion/ServiceNavigationActivity.java`
- `backend/tests/test_navigation.py`

### 关联接口或符号

- `GET /api/v1/services/{service_id}/navigation-options`
- `POST /api/v1/admin/navigation-catalog/import?dry_run=true|false`
- `NavigationCatalogCoordinator`
- `HuaweiNaviEngineAdapter`
- `NavigationStateMachine`
- `NearbyWindowSelector`

## 可信输入

Compose、数字人和 WebView 只能传递服务端签发或目录返回的 `service_id`，不得直接控制坐标、包名、URI 或 Intent。

## 路线状态

状态机覆盖网点就绪、定位、算路、路线预览、正在启动、导航中、到达和失败；只有算路成功后才开放启动。

## 隐私边界

用户位置只进入 Location Kit、距离排序和 Navi SDK，不上传项目 API、不持久化且不写应用日志。
