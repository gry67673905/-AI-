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
        self._seed_password_hashes: tuple[str, str] | None = None
        self.repository = BusinessRepository(sessions)
        self.object_store = MinioObjectStore(
            settings.minio_endpoint,
            settings.minio_access_key.get_secret_value(),
            settings.minio_secret_key.get_secret_value(),
            settings.materials_bucket,
            settings.knowledge_bucket,
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
        self.consultations = ConsultationCoordinator(
            self.repository,
            persistence,
            cache,
            government_tools,
            knowledge_retrieval or milvus,
            model,
            self.security,
        )
        self.applications = ApplicationCoordinator(
            self.repository,
            self.object_store,
            self.idempotency,
            settings.max_material_bytes,
        )
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
            await self.repository.recover_stale_knowledge_jobs()
            # Existing persistent volumes may contain vectors written before
            # the ACTIVE dynamic field was introduced. Re-upsert authoritative
            # PostgreSQL ACTIVE chunks so upgrades preserve searchable data.
            active_chunks = await self.repository.list_active_knowledge_chunks()
            if active_chunks:
                await self.vector_index.activate_chunks(active_chunks)
            self._startup_complete = True
