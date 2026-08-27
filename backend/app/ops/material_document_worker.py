from __future__ import annotations

import asyncio
import signal
from pathlib import Path

from app.application.material_documents import MaterialDocumentWorker
from app.config import Settings, get_settings
from app.database import Database
from app.infrastructure.material_documents import (
    DashScopeMaterialTemplateAnalyzer,
    DeterministicDocxMaterialRenderer,
    LibreOfficeTemplatePageRenderer,
    MockMaterialTemplateAnalyzer,
)
from app.infrastructure.object_store import MinioObjectStore
from app.infrastructure.repositories import BusinessRepository
from app.infrastructure.secrets import secret_value
from app.ops.material_template_import import import_material_templates


HEARTBEAT_PATH = Path("/tmp/material-worker.heartbeat")


async def _heartbeat(stop: asyncio.Event) -> None:
    while not stop.is_set():
        HEARTBEAT_PATH.write_text("ok\n", encoding="ascii")
        try:
            await asyncio.wait_for(stop.wait(), timeout=5.0)
        except TimeoutError:
            pass


async def run(settings: Settings) -> None:
    if not settings.material_documents_enabled:
        raise RuntimeError("MATERIAL_DOCUMENTS_ENABLED must be true")
    await import_material_templates(settings)
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
    if settings.material_template_provider == "dashscope":
        analyzer = DashScopeMaterialTemplateAnalyzer(
            secret_value(
                settings.material_template_dashscope_api_key,
                settings.material_template_dashscope_api_key_file,
            ),
            model_name=settings.material_template_model,
            base_url=settings.material_template_dashscope_base_url,
            timeout_seconds=settings.material_document_model_timeout_seconds,
        )
    else:
        analyzer = MockMaterialTemplateAnalyzer()
    worker = MaterialDocumentWorker(
        repository,
        store,
        analyzer,
        LibreOfficeTemplatePageRenderer(max_pages=12),
        DeterministicDocxMaterialRenderer(),
        lease_seconds=settings.material_document_worker_lease_seconds,
        release_lane=settings.material_document_release_lane,
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:
                pass
    try:
        await database.ping()
        await store.ping()
        heartbeat_task = asyncio.create_task(
            _heartbeat(stop), name="material-worker-heartbeat"
        )
        while not stop.is_set():
            worked = await worker.run_once()
            if worked:
                await asyncio.sleep(0)
                continue
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=settings.material_document_worker_poll_seconds,
                )
            except TimeoutError:
                pass
    finally:
        stop.set()
        if "heartbeat_task" in locals():
            await asyncio.gather(heartbeat_task, return_exceptions=True)
        await analyzer.close()
        await database.dispose()


def main() -> None:
    asyncio.run(run(get_settings()))


if __name__ == "__main__":
    main()
