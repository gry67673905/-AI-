# docs(workflow): 补录办件状态机验收

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

## 正向链路

记录从草稿到提交、审核和结果的合成演示验收路径。

## 负向链路

覆盖字段缺失、材料不足、版本冲突、跨用户、状态跳级和终态复活拒绝。

## 非真实能力声明

明确支付、核验、邮寄和审批结果均为模拟，不用于真实办事。
