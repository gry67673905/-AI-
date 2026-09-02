# docs(db): 追踪导航与材料能力加法迁移

> 课程验收补录 / retrospective evidence：内容依据仓库在 GitHub 实际创建时的代码、接口、文档与测试整理；它不倒填历史日期、不伪造原开发过程，完成与未完成状态均按证据如实标注。

## 证据边界

本文件针对“数据库与迁移”整理当前仓库可核查事实；它不是原开发日期的伪造记录。

### 关联路径

- `backend/migrations/versions/0001_initial.py`
- `backend/migrations/versions/0007_navigation_catalog.py`
- `backend/migrations/versions/0008_material_documents.py`
- `backend/migrations/versions/0009_consultation_material_documents.py`
- `backend/app/infrastructure/records.py`

### 关联接口或符号

- Alembic revision 0001_initial
- Alembic revision 0007_navigation_catalog
- Alembic revision 0008_material_documents
- Alembic revision 0009_consultation_materials
- `BusinessRepository`

## 问题与约束

记录导航目录、异步材料任务和咨询模板意图需要新增持久化结构的背景。

## 修正链路

关联 0007 导航目录、0008 材料文档、0009 咨询材料意图和 repository 映射。

## 数据保护

说明匿名会话兼容、历史办件保留以及迁移不删除用户数据的边界。
