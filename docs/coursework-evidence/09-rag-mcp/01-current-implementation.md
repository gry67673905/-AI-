# docs(rag): 记录组合检索与只读 MCP 实现

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

## 来源组成

说明 PostgreSQL local_catalog、MCP 公开目录、本地知识和团队语料各自来源与可信边界。

## 索引结构

记录 256 维本地知识、1024 维团队语料、版本别名和 RRF 融合。

## MCP 边界

列出只读工具职责并说明写操作、任意 URL 和私人办件上下文不进入 MCP。
