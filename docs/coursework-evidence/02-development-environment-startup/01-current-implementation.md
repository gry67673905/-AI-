# docs(dev): 记录本地 Compose 服务拓扑

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

## 拓扑概览

逐项说明 PostgreSQL、Redis、Milvus、MinIO、Mock API、MCP、FastAPI 与后台任务在本地栈中的作用。

## 网络边界

区分宿主可访问端口与仅 Compose 网络可达的服务，避免把内部依赖暴露为公网接口。

## 数据保留

说明普通停止与删除命名卷的差异，提醒后者具有不可恢复的数据影响。
