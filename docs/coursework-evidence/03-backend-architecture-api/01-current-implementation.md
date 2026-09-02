# docs(api): 记录后端 BCE 分层与运行边界

> 课程验收补录 / retrospective evidence：内容依据仓库在 GitHub 实际创建时的代码、接口、文档与测试整理；它不倒填历史日期、不伪造原开发过程，完成与未完成状态均按证据如实标注。

## 证据边界

本文件针对“后端架构与 API”整理当前仓库可核查事实；它不是原开发日期的伪造记录。

### 关联路径

- `backend/app/main.py`
- `backend/app/boundaries/http.py`
- `backend/app/application/coordinators.py`
- `docs/architecture.md`

### 关联接口或符号

- `create_app`
- `build_business_router`
- `BusinessRepositoryPort`
- `GET /health/live`
- `GET /health/ready`

## 应用入口

说明 create_app 的 lifespan、异常处理、健康端点和业务 router 装配职责。

## 分层关系

以 boundary、coordinator、domain、port、adapter 的真实模块说明允许的依赖方向。

## 可信边界

记录客户端、模型与外部服务输入必须经过 schema、鉴权和领域规则后才可写入。
