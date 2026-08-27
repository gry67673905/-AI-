from __future__ import annotations

import argparse
import asyncio

from app.config import Settings, get_settings
from app.database import Database
from app.infrastructure.material_documents import MaterialTemplatePack
from app.infrastructure.material_template_catalog import (
    immutable_material_template_objects,
)
from app.infrastructure.object_store import MinioObjectStore
from app.infrastructure.repositories import BusinessRepository


async def import_material_templates(settings: Settings) -> int:
    database = Database(settings.database_url)
    store = MinioObjectStore(
        settings.minio_endpoint,
        settings.minio_access_key.get_secret_value(),
        settings.minio_secret_key.get_secret_value(),
        settings.materials_bucket,
        settings.knowledge_bucket,
        settings.material_templates_bucket,
        settings.generated_documents_bucket,
    )
    repository = BusinessRepository(database.sessions)
    try:
        await database.ping()
        await store.ensure_buckets()
        templates = immutable_material_template_objects(
            MaterialTemplatePack(
                settings.material_template_manifest_path,
                settings.material_template_source_prefix,
            ).load()
        )
        for template in templates:
            if template.source_bytes is None or template.source_object_key is None:
                continue
            await store.put_bytes(
                store.material_templates_bucket,
                template.source_object_key,
                template.source_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        await repository.seed_material_templates(templates)
        return len(templates)
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import the reviewed material-template pack"
    )
    parser.parse_args()
    count = asyncio.run(import_material_templates(get_settings()))
    print(f"imported material template catalog entries: {count}")


if __name__ == "__main__":
    main()
