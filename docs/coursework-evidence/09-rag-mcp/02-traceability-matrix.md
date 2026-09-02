# docs(rag): 建立检索缓存与来源追踪矩阵

> 课程验收补录 / retrospective evidence：内容依据仓库在 GitHub 实际创建时的代码、接口、文档与测试整理；它不倒填历史日期、不伪造原开发过程，完成与未完成状态均按证据如实标注。

## 证据边界

本文件针对“RAG 与 MCP”整理当前仓库可核查事实；它不是原开发日期的伪造记录。

### 关联路径

- `backend/app/infrastructure/composite_retriever.py`
- `backend/app/application/rag_import.py`
- `mcp-server/src/tools.js`
- `mcp-server/tests/server.test.js`

### 关联接口或符号

- `CompositeKnowledgeRetriever`
- `RagCorpusImportCoordinator`
- `SqlAlchemyCorpusRepository`
- `VersionedMilvusCorpusIndex`
- `searchServices`
- `getServiceDetails`

## 查询输入

记录当前问题、外部事项映射与 dataset 版本如何形成隔离的检索上下文。

## 并行检索

映射 MCP、本地知识和团队语料适配器及其独立失败行为。

## 融合与输出

说明 RRF、来源去重、Redis v3 缓存和 ChatSource 返回路径。
