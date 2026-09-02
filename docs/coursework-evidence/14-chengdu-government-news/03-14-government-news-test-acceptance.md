# 政务消息测试与运维验收计划

> 课程验收补录 / retrospective evidence：内容依据仓库在 GitHub 实际创建时的代码、接口、文档与测试整理；它不倒填历史日期、不伪造原开发过程，完成与未完成状态均按证据如实标注。

## 证据边界

本文件针对“成都政务消息”整理当前仓库可核查事实；它不是原开发日期的伪造记录。

### 关联路径

- `README.md`
- `backend/app/boundaries/http.py`
- `backend/app/infrastructure/records.py`
- `android/app/src/main/assets/index.html`
- `android/app/src/main/assets/portal-app-v2.js`

### 关联接口或符号

- `build_business_router`
- `PortalJsBoundary`
- `GET /api/v1/services`
- `GET /api/v1/consultations`
- government-news routes absent at frozen main

## 解析测试

计划中的固件测试应覆盖编码、日期、正文清洗、XSS、内容更新、304、超时、响应大小和不安全重定向；该快照无通过结果。

## API 与客户端测试

计划中的接口测试覆盖分类、游标、详情和匿名访问；客户端契约覆盖固定路径、分页去重、安全渲染和原文命令。

## 运行限制

未来实现应在外站失败时继续提供已有数据，且不把 readiness 与单次抓取绑定；本文明确这些是验收目标而非现有结果。
