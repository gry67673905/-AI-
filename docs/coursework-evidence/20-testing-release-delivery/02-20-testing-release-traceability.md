# 功能域与测试追踪矩阵

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

## 需求映射

矩阵按 20 个 Epic 关联对应单元、契约、集成、烟测和人工验收，避免仅以总测试数量衡量质量。

## 环境标识

每条测试证据记录本地 Mock、固定固件、候选云端或真机环境，并说明外部依赖和计费影响。

## 结果规则

通过、失败、跳过和未验证分别记录；报告不把跳过的真机或供应商测试合并到自动化通过结论。
