# docs(governance): 记录仓库组成与演示边界

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

## 补录说明

本文为课程验收补录，依据当前 README 与目录结构整理，不代表这些记录在功能开发当日已经创建。

## 仓库组成

说明 Android 客户端、FastAPI 模块化单体、只读 MCP、Mock API、Compose 依赖与部署资料各自职责，并给出真实路径。

## 产品边界

记录合成演示数据、非正式政务平台、模型不得直接改变业务状态等已存在约束。
