# docs(governance): 建立入口与质量脚本追踪矩阵

> 课程验收补录 / retrospective evidence：内容依据仓库在 GitHub 实际创建时的代码、接口、文档与测试整理；它不倒填历史日期、不伪造原开发过程，完成与未完成状态均按证据如实标注。

## 证据边界

本文件针对“仓库治理”整理当前仓库可核查事实；它不是原开发日期的伪造记录。

### 关联路径

- `README.md`
- .gitignore
- `scripts/test-all.ps1`

### 关联接口或符号

- `scripts/test-all.ps1`
- `scripts/show-demo-accounts.ps1`
- `GET /health/ready`

## 运行入口

把初始化、启动、停止、日志、健康检查和演示账号命令映射到 scripts 下的实际脚本。

## 测试入口

解释 test-all、smoke 与业务 smoke 的覆盖范围、前置条件和副作用差异。

## 可追踪结论

列出每条仓库说明对应的文件或 HTTP 健康端点，便于课程复核。
