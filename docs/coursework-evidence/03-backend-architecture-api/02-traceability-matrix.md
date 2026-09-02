# docs(api): 建立公共接口调用追踪矩阵

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

## 接口分组

按认证、群众办件、工作人员、管理员、咨询和运维列出代表性方法与路径。

## 调用链

将代表性路径映射到 Pydantic schema、HTTP boundary、用例协调者和存储端口。

## 授权与错误

标记匿名可用性、角色要求、幂等头和主要结构化错误。
