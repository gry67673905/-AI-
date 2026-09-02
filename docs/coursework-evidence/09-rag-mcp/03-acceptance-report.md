# docs(rag): 补录只读工具与融合检索验收

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

## MCP 验收

引用 Node 测试说明工具白名单、Bearer 边界、参数校验和只读调用。

## RAG 验收

记录维度隔离、版本导入、融合排序、缓存键和单后端故障降级。

## 数据声明

明确仓库知识与团队语料均为演示参考，不构成真实政策依据。
