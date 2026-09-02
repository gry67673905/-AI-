# docs(db): 补录迁移回归验收结果

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

## 结构验收

列出 0001 至 0009 revision 连续性、新表约束和索引的静态检查。

## 数据验收

记录旧办件、匿名会话和既有材料引用在加法迁移中的保留边界。

## 限制

明确自动化证据不替代部署前备份和独立恢复演练。
