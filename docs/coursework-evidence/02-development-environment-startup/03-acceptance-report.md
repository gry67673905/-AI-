# docs(dev): 补录本地启动验收场景

> 课程验收补录 / retrospective evidence：内容依据仓库在 GitHub 实际创建时的代码、接口、文档与测试整理；它不倒填历史日期、不伪造原开发过程，完成与未完成状态均按证据如实标注。

## 证据边界

本文件针对“开发环境与启动”整理当前仓库可核查事实；它不是原开发日期的伪造记录。

### 关联路径

- `compose.yaml`
- `scripts/init-env.ps1`
- `scripts/dev-up.ps1`
- `scripts/dev-down.ps1`

### 关联接口或符号

- docker compose up
- `GET /health/live`
- `GET /health/ready`
- `AppServices.startup`

## 正常场景

描述配置初始化、完整栈启动和 readiness 成功的可重复检查过程。

## 异常场景

记录缺失配置、依赖未就绪和端口冲突时应观察的安全错误边界。

## 停止场景

确认 dev-down 的常规用途，并明确验收不执行删除卷操作。
