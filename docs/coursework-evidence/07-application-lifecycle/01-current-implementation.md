# docs(workflow): 记录办件与审核生命周期

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

## 群众流程

描述草稿、表单、预审、材料、提交、补正、撤回和进度查看。

## 工作人员流程

说明任务认领、审核决定、补正和终态处理的授权与状态约束。

## 扩展操作

记录预约、模拟缴费、核验和投递由独立协调者处理且全部为演示能力。
