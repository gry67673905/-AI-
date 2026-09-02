# docs(db): 记录权威数据模型与迁移演进

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

## 存储职责

说明 PostgreSQL、Redis、Milvus 与 MinIO 各自承载的状态，强调 PostgreSQL 的权威边界。

## 迁移序列

按 0001 至 0009 概括账号目录、业务操作、知识、RAG、MetaStudio、导航、材料和咨询模板演进。

## 不可变历史

说明事项版本和已提交办件引用为何不能原地改写。
