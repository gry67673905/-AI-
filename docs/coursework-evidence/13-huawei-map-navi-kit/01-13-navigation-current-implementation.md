# 华为地图与 Navi Kit 当前实现说明

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

## 补录说明

本文依据当前导航目录、Android Activity 和华为适配器整理，不把 DEMO 路线描述为真实政务出行服务。

## 服务端目录

后端以事项 ID 返回活动网点及 GCJ02 坐标，并通过管理员 CSV 接口提供 dry-run 和原子导入；来源 URL 与设备位置不进入该接口。

## 设备端导航

设备取得一次前台定位，在本地选择最近网点，再由华为 Navi Kit 进行步行或驾车算路、地图预览和逐向引导。
