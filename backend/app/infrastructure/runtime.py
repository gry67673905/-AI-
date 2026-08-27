from __future__ import annotations

import asyncio
from typing import Any

from app.application.coordinators import (
    AdminCoordinator,
    ApplicationCoordinator,
    AppointmentCoordinator,
    AuthCoordinator,
    CatalogCoordinator,
    ConsultationCoordinator,
    DeliveryCoordinator,
    HandoffCoordinator,
    IdempotencyCoordinator,
    KnowledgeIndexCoordinator,
    PaymentCoordinator,
    ReviewCoordinator,
    VerificationCoordinator,
)
from app.application.metastudio import MetaStudioCoordinator
from app.application.navigation import NavigationCatalogCoordinator
from app.application.vision import VisionCoordinator
from app.application.material_documents import MaterialDocumentCoordinator
from app.application.ports import (
    ChatModelPort,
    ChatPersistencePort,
    GovernmentToolRetrievalPort,
    KnowledgeRetrievalPort,
    KnowledgeVectorPort,
    PublicRetrievalCachePort,
)
from app.config import Settings
from app.infrastructure.object_store import MinioObjectStore
from app.infrastructure.document_parser import LocalKnowledgeParser
from app.infrastructure.providers import (
    DemoDeliveryProvider,
    DemoFaceVerificationProvider,
    DemoPaymentProvider,
    DemoSmsProvider,
)
from app.infrastructure.repositories import BusinessRepository
from app.infrastructure.security_adapter import LocalSecurityAdapter
from app.infrastructure.metastudio import (
    HuaweiMetaStudioOnceCodeAdapter,
    MetaStudioCallbackAuthenticator,
    RedisMetaStudioSessionAdapter,
)
from app.infrastructure.secrets import secret_value
from app.infrastructure.vision import (
    DashScopeVisionAnalyzer,
    HttpVisionEventAnalyzer,
    InMemoryVisionFrameStore,
    MockVisionAnalyzer,
    MockVisionEventAnalyzer,
    RedisVisionAnalysisQuota,
    RedisVisionTicketAdapter,
)
from app.infrastructure.material_documents import (
    MaterialTemplatePack,
    MockMaterialTemplateAnalyzer,
)
from app.infrastructure.material_template_catalog import (
    immutable_material_template_objects,
)


class BusinessRuntime:
    """Infrastructure composition root for the modular monolith."""

    def __init__(
        self,
        settings: Settings,
        sessions: Any,
        persistence: ChatPersistencePort,
        cache: PublicRetrievalCachePort,
        government_tools: GovernmentToolRetrievalPort,
        milvus: KnowledgeVectorPort,
        model: ChatModelPort,
        knowledge_retrieval: KnowledgeRetrievalPort | None = None,
    ) -> None:
        environment = settings.environment.strip().lower()
        if environment == "demo" and settings.enable_demo_providers:
            acknowledgement = (
                settings.demo_provider_ack.get_secret_value()
                if settings.demo_provider_ack is not None
                else ""
            )
            if acknowledgement != "I_ACKNOWLEDGE_DEMO_PROVIDERS":
                raise RuntimeError(
                    "ENVIRONMENT=demo requires explicit DEMO_PROVIDER_ACK"
                )
        elif environment != "local" and settings.enable_demo_providers:
            raise RuntimeError(
                "Demo providers may only be enabled in ENVIRONMENT=local or acknowledged demo"
            )
        enabled = environment in {"local", "demo"} and settings.enable_demo_providers
        self.settings = settings
        self._startup_lock = asyncio.Lock()
        self._startup_complete = False
        self._vision_cleanup_task: asyncio.Task[None] | None = None
        self._seed_password_hashes: tuple[str, str] | None = None
        self.repository = BusinessRepository(sessions)
        self.object_store = MinioObjectStore(
            settings.minio_endpoint,
            settings.minio_access_key.get_secret_value(),
            settings.minio_secret_key.get_secret_value(),
            settings.materials_bucket,
            settings.knowledge_bucket,
            settings.material_templates_bucket,
            settings.generated_documents_bucket,
        )
        self._packed_material_templates = (
            immutable_material_template_objects(
                MaterialTemplatePack(
                    settings.material_template_manifest_path,
                    settings.material_template_source_prefix,
                ).load()
            )
            if settings.material_documents_enabled
            else ()
        )
        self.sms = DemoSmsProvider(enabled, settings.demo_sms_code.get_secret_value())
        self.payment_provider = DemoPaymentProvider(enabled)
        self.verification_provider = DemoFaceVerificationProvider(enabled)
        self.delivery_provider = DemoDeliveryProvider(enabled)
        self.security = LocalSecurityAdapter(
            settings.jwt_signing_key.get_secret_value(),
            settings.jwt_access_minutes,
        )
        self.knowledge_parser = LocalKnowledgeParser()
        self.vector_index = milvus
        self.auth = AuthCoordinator(
            self.repository,
            self.security,
            self.sms,
            settings.jwt_refresh_days,
            settings.demo_sms_code.get_secret_value(),
        )
        self.idempotency = IdempotencyCoordinator(self.repository)
        self.catalog = CatalogCoordinator(self.repository)
        self.navigation = NavigationCatalogCoordinator(self.repository)
        self.consultations = ConsultationCoordinator(
            self.repository,
            persistence,
            cache,
            government_tools,
            knowledge_retrieval or milvus,
            model,
            self.security,
        )
        self.metastudio_sessions = RedisMetaStudioSessionAdapter(settings.redis_url)
        self.vision_tickets = RedisVisionTicketAdapter(settings.redis_url)
        self.vision_frames = InMemoryVisionFrameStore(
            ttl_seconds=settings.vision_frame_ttl_seconds,
            max_sessions=settings.vision_max_sessions,
            max_frames_per_session=settings.vision_max_frames_per_session,
            max_total_bytes=settings.vision_max_total_bytes,
            min_frame_interval_ms=settings.vision_min_frame_interval_ms,
            sealed_turn_capacity=settings.vision_sealed_turn_capacity,
            timeline_ttl_seconds=settings.vision_timeline_ttl_seconds,
            max_timeline_events=settings.vision_timeline_max_events,
        )
        if settings.vision_fast_provider == "http":
            if not settings.vision_fast_http_url:
                raise RuntimeError(
                    "VISION_FAST_HTTP_URL is required for VISION_FAST_PROVIDER=http"
                )
            self.vision_fast_analyzer = HttpVisionEventAnalyzer(
                settings.vision_fast_http_url,
                timeout_seconds=settings.vision_fast_timeout_seconds,
            )
        else:
            self.vision_fast_analyzer = MockVisionEventAnalyzer()
        if settings.vision_provider == "dashscope":
            self.vision_analysis_quota = RedisVisionAnalysisQuota(
                settings.redis_url,
                daily_limit=settings.vision_analysis_global_daily,
            )
            self.vision_analyzer = DashScopeVisionAnalyzer(
                secret_value(
                    settings.vision_dashscope_api_key,
                    settings.vision_dashscope_api_key_file,
                ),
                quota=self.vision_analysis_quota,
                base_url=settings.vision_dashscope_base_url,
                document_timeout_seconds=settings.vision_document_timeout_seconds,
            )
        else:
            self.vision_analysis_quota = None
            self.vision_analyzer = MockVisionAnalyzer()
        self.metastudio_once_codes = HuaweiMetaStudioOnceCodeAdapter(
            enabled=settings.metastudio_enabled,
            endpoint=settings.metastudio_once_code_endpoint,
            project_id=settings.metastudio_project_id,
            access_key=secret_value(
                settings.metastudio_huawei_access_key,
                settings.metastudio_huawei_access_key_file,
            ),
            secret_key=secret_value(
                settings.metastudio_huawei_secret_key,
                settings.metastudio_huawei_secret_key_file,
            ),
            timeout_seconds=settings.metastudio_http_timeout_seconds,
        )
        self.metastudio_authenticator = MetaStudioCallbackAuthenticator(
            enabled=settings.metastudio_enabled,
            app_id=settings.metastudio_app_id,
            app_key=secret_value(
                settings.metastudio_app_key, settings.metastudio_app_key_file
            ),
            callback_url=settings.metastudio_callback_url,
            replay_window_seconds=settings.metastudio_replay_window_seconds,
            sessions=self.metastudio_sessions,
        )
        self.metastudio = MetaStudioCoordinator(
            self.repository,
            self.consultations,
            self.metastudio_sessions,
            self.metastudio_once_codes,
            pii_hmac_key=settings.pii_hmac_key.get_secret_value(),
            robot_id=settings.metastudio_robot_id,
            server_address=settings.metastudio_server_address,
            context_ttl_seconds=settings.metastudio_context_ttl_seconds,
            action_intent_ttl_seconds=settings.metastudio_action_intent_ttl_seconds,
            vision=None,
        )
        # The vision ticket is meaningful only while the owning MetaStudio
        # client session is live.  Compose the two coordinators in this order
        # so there is one authoritative owner/role/token-version check before
        # a short-lived camera ticket can be minted.
        self.vision = VisionCoordinator(
            self.vision_tickets,
            self.vision_frames,
            self.vision_analyzer,
            enabled=settings.vision_enabled,
            ticket_ttl_seconds=settings.vision_ticket_ttl_seconds,
            authorize_client_session=self.metastudio.authorize_client_session,
            turn_close_wait_ms=settings.vision_turn_close_wait_ms,
            fast_analyzer=self.vision_fast_analyzer,
            fast_max_concurrency=settings.vision_fast_max_concurrency,
            late_memory_ttl_seconds=settings.vision_late_memory_ttl_seconds,
        )
        self.metastudio.vision = self.vision
        self.applications = ApplicationCoordinator(
            self.repository,
            self.object_store,
            self.idempotency,
            settings.max_material_bytes,
        )
        self.material_documents = MaterialDocumentCoordinator(
            self.repository,
            self.object_store,
            self.idempotency,
            enabled=settings.material_documents_enabled,
            retention_hours=settings.material_document_retention_hours,
            model_name=(
                settings.material_template_model
                if settings.material_template_provider == "dashscope"
                else MockMaterialTemplateAnalyzer.model_name
            ),
            release_lane=settings.material_document_release_lane,
            user_daily_limit=settings.material_document_user_daily_limit,
            user_active_limit=settings.material_document_user_active_limit,
            global_daily_limit=settings.material_document_global_daily_limit,
            global_queue_limit=settings.material_document_global_queue_limit,
        )
        # Consultation chat may discover templates and mint a short-lived
        # confirmation intent, but it never confirms or starts generation.
        self.consultations.material_documents = self.material_documents
        self.reviews = ReviewCoordinator(self.repository, self.idempotency)
        self.handoffs = HandoffCoordinator(self.repository, self.idempotency)
        self.appointments = AppointmentCoordinator(self.repository, self.idempotency)
        self.payments = PaymentCoordinator(
            self.repository, self.payment_provider, self.idempotency
        )
        self.verifications = VerificationCoordinator(
            self.repository, self.verification_provider, self.idempotency
        )
        self.deliveries = DeliveryCoordinator(
            self.repository, self.delivery_provider, self.security,
            self.idempotency,
        )
        self.knowledge = KnowledgeIndexCoordinator(
            self.repository, self.object_store, milvus,
            self.knowledge_parser, self.idempotency, cache,
        )
        self.admin = AdminCoordinator(
            self.repository, self.security, self.idempotency
        )

    async def startup(self) -> None:
        # Readiness may retry a failed seed and several probes may arrive at
        # once. Only one coroutine performs initialization in this process;
        # successful initialization becomes a no-op for later probes.
        async with self._startup_lock:
            if self._startup_complete:
                return
            await self.object_store.ensure_buckets()
            if self._seed_password_hashes is None:
                # Argon2id is intentionally expensive and CPU-bound. Keep it
                # off the event loop and cache the hashes across retries.
                admin_hash, staff_hash = await asyncio.gather(
                    asyncio.to_thread(
                        self.security.hash_password,
                        self.settings.demo_admin_password.get_secret_value(),
                    ),
                    asyncio.to_thread(
                        self.security.hash_password,
                        self.settings.demo_staff_password.get_secret_value(),
                    ),
                )
                self._seed_password_hashes = (admin_hash, staff_hash)
            await self.repository.seed_demo_catalog(
                self.settings.demo_admin_username,
                self._seed_password_hashes[0],
                self.settings.demo_staff_username,
                self._seed_password_hashes[1],
            )
            packed_templates = getattr(
                self, "_packed_material_templates", ()
            )
            for template in packed_templates:
                if (
                    template.source_bytes is not None
                    and template.source_object_key is not None
                ):
                    await self.object_store.put_bytes(
                        self.object_store.material_templates_bucket,
                        template.source_object_key,
                        template.source_bytes,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
            if packed_templates:
                await self.repository.seed_material_templates(packed_templates)
            await self.repository.recover_stale_knowledge_jobs()
            # Existing persistent volumes may contain vectors written before
            # the ACTIVE dynamic field was introduced. Re-upsert authoritative
            # PostgreSQL ACTIVE chunks so upgrades preserve searchable data.
            active_chunks = await self.repository.list_active_knowledge_chunks()
            if active_chunks:
                await self.vector_index.activate_chunks(active_chunks)
            if (
                self.settings.vision_enabled
                and self._vision_cleanup_task is None
            ):
                self._vision_cleanup_task = asyncio.create_task(
                    self._vision_cleanup_loop(),
                    name="metastudio-vision-frame-ttl",
                )
            self._startup_complete = True

    async def _vision_cleanup_loop(self) -> None:
        interval = max(
            0.25,
            min(1.0, self.settings.vision_frame_ttl_seconds / 4),
        )
        while True:
            await asyncio.sleep(interval)
            try:
                await self.vision.cleanup_expired()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Cleanup is memory-local and retried on the next short tick;
                # it must not take down the API or emit image-derived logs.
                continue

    async def close(self) -> None:
        cleanup_task = self._vision_cleanup_task
        self._vision_cleanup_task = None
        if cleanup_task is not None:
            cleanup_task.cancel()
            await asyncio.gather(cleanup_task, return_exceptions=True)
        await self.vision.close()
        tasks = [
            self.metastudio_sessions.close(),
            self.vision_tickets.close(),
            self.metastudio_once_codes.close(),
        ]
        close_vision_analyzer = getattr(self.vision_analyzer, "close", None)
        if callable(close_vision_analyzer):
            tasks.append(close_vision_analyzer())
        close_fast_vision_analyzer = getattr(
            self.vision_fast_analyzer, "close", None
        )
        if callable(close_fast_vision_analyzer):
            tasks.append(close_fast_vision_analyzer())
        if self.vision_analysis_quota is not None:
            tasks.append(self.vision_analysis_quota.close())
        await asyncio.gather(*tasks, return_exceptions=True)
