# 测试、构建与交付当前实现说明

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

## 补录说明

本文汇总仓库当前测试与交付入口，并保留测试执行时间的真实性；未在本次补录中运行的命令不会标为通过。

## 自动化层级

冻结 main 包含 Python 后端、Node MCP/Mock、Android JVM、lint 和 APK 构建等层级；Compose instrumentation 不存在于该快照。

## 交付边界

云端烟测和真机供应商能力属于额外门禁；debug APK、合成业务和 DEMO 数据在报告与界面中保持明确标注。
