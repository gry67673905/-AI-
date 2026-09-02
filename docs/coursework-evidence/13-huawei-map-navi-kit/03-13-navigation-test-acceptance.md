# 导航测试与演示验收报告

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

## 自动化覆盖

后端测试目录关系、CSV 校验和发布状态；Android 测试最近三个排序、权限、超时、华为初始化、启动仲裁和引导状态。

## 真机门禁

真实路线验收依赖 Android 设备、HMS Core、网络和 GPS；应分别检查步行、驾车、中文语音、退出清理及安全环境下的偏航。

## 数据声明

课程演示所用成都点位为虚构 DEMO 数据，页面与报告持续显示“不用于实际出行”，避免误导用户。
