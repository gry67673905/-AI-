# 政务消息拟议数据与接口矩阵

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

## 来源契约

拟议来源代码、名称、分类和解析规则应由代码拥有；数据库只管理状态和条件请求元数据，不能注入任意 URL。

## 消息契约

拟议消息应以官方标识、URL 哈希和内容哈希去重；正文上限和类型校验用于限制异常响应。

## API 契约

拟议列表、详情和受控 source 跳转允许匿名读取；管理员接口只返回来源健康状态。冻结 main 尚无这些路由。
