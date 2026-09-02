# docs(api): 补录契约与异常处理验收

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

## 契约检查

引用现有 OpenAPI 和 API 测试，记录校验、鉴权、冲突、配额和依赖失败的状态码。

## 敏感输入

说明 RequestValidationError 被转换为不含 rejected input 的安全结构。

## 结论与限制

区分已有自动化证据与仍需真机或真实提供商验证的边界。
