from uuid import uuid4

from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.infrastructure.records import KnowledgeCorpusChunkRecord


def test_corpus_bulk_insert_uses_mapped_metadata_attribute() -> None:
    """Guard the ORM key/SQL column-name distinction used by real PostgreSQL."""

    statement = pg_insert(KnowledgeCorpusChunkRecord).values(
        [
            {
                "id": uuid4(),
                "dataset_id": uuid4(),
                "external_id": "chunk-1",
                "topic_slug": "t01",
                "topic_name": "演示主题",
                "document_title": "演示事项",
                "section": "正文",
                "chunk_type": "正文",
                "theme": None,
                "content": "演示内容",
                "source_content_hash": "a" * 64,
                "content_hash": "b" * 64,
                "status": "PENDING",
                "metadata_json": {"demo_data": True},
            }
        ]
    )

    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "knowledge_corpus_chunks" in sql
    assert "metadata" in sql
