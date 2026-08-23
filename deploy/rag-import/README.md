# 团队 RAG 云导入

`rag-import` 属于 `ops` profile，默认不会随服务启动。它只读取净化后的 `group-rag-sanitized-v1.zip`，校验固定 SHA-256 和 15858 个分块，再调用 DashScope `text-embedding-v4` 写入版本化 Milvus collection 并原子切换 alias。

不要上传原始 `RAG_DATABASE .zip`，它包含已废弃凭据和未经净化的非业务文件。云端只允许使用 `artifacts/rag/group-rag-sanitized-v1.zip`，且 SHA-256 必须为 `b5221f51465a230192148cb8e3db81a81e21348809a2738ca8ce89d8f6543f93`。

首次部署必须保持 `RAG_GROUP_ENABLED=false`，让 API 在不依赖新语料的情况下完成迁移并通过 7 项 readiness。确认一次性 embedding 费用后，以 root 执行：

```bash
deploy/scripts/import-rag.sh --confirm-paid-import
```

脚本先做零网络/零写入的压缩包校验，再执行真实导入；只有导入成功后才将固定版本写入 `deploy/cloud.env`、重建 API，并要求含 `rag_corpus` 的 8 项 readiness 全部通过。失败时保留旧 alias，不会自动启用未就绪语料。
