# docs(workflow): 建立表单材料与状态追踪矩阵

> 课程验收补录 / retrospective evidence：内容依据仓库在 GitHub 实际创建时的代码、接口、文档与测试整理；它不倒填历史日期、不伪造原开发过程，完成与未完成状态均按证据如实标注。

## 证据边界

本文件针对“办件生命周期”整理当前仓库可核查事实；它不是原开发日期的伪造记录。

### 关联路径

- `backend/app/application/coordinators.py`
- `backend/app/domain/entities.py`
- `backend/app/domain/policies.py`
- `backend/tests/test_domain_business.py`

### 关联接口或符号

- `ApplicationCoordinator`
- `ReviewCoordinator`
- `AppointmentCoordinator`
- `PaymentCoordinator`
- `POST /api/v1/applications`
- `POST /api/v1/applications/{application_id}/submit`
- `POST /api/v1/applications/{application_id}/withdraw`

## 输入契约

关联事项 form_schema、eligibility、material requirements 与办件 form_data。

## 状态写入

列出创建、更新、提交、补正、撤回、审核和完成对应的 version 与 Idempotency-Key 要求。

## 存储与审计

说明办件、材料、任务和事件如何在同一权威数据库中关联。
