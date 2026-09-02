# docs(dev): 追踪初始化到 readiness 的启动链路

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

## 初始化

记录 init-env 的职责以及生成配置不进入证据文档和版本控制的约束。

## 应用启动

关联 dev-up、FastAPI lifespan 和 AppServices.startup 的真实代码位置。

## 健康语义

说明 health/live 只代表进程，health/ready 聚合外部依赖与业务种子状态。
