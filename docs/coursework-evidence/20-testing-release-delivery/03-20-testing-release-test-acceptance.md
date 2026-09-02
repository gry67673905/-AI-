# 候选版本与演示验收报告

> 课程验收补录 / retrospective evidence：内容依据仓库在 GitHub 实际创建时的代码、接口、文档与测试整理；它不倒填历史日期、不伪造原开发过程，完成与未完成状态均按证据如实标注。

## 证据边界

本文件针对“测试、发布与交付”整理当前仓库可核查事实；它不是原开发日期的伪造记录。

### 关联路径

- `scripts/test-all.ps1`
- `backend/tests/test_api.py`
- `android/app/build.gradle`
- `android/app/src/test/java/com/example/aicompanion/portal/coordinator/PortalCoordinatorViewModelTest.java`
- `deploy/scripts/verify-cloud-smoke.sh`

### 关联接口或符号

- `scripts/test-all.ps1`
- python -m pytest -q
- :app:testDebugUnitTest
- :app:lintDebug
- :app:assembleDebug
- `verify-cloud-smoke.sh`

## 候选构建

候选流程运行适用测试、lint 和 assembleDebug，随后核对 APK 签名、内置 HTTPS 基址、大小、SHA-256 与秘密扫描。

## 真机验收

指定唯一设备后覆盖安装且不清数据，依次验证三角色认证、办件、AI、材料、数字人、视觉、Navi 与政务消息。

## 交付声明

最终报告列出已通过、未验证和外部阻塞项，并持续说明该版本为成都合成演示服务而非正式政府生产平台。
