from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded exclusively from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "smart-gov-api"
    environment: str = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://smartgov:smartgov@postgres:5432/smartgov"
    redis_url: str = "redis://redis:6379/0"
    cache_ttl_seconds: int = Field(default=300, ge=1, le=86_400)

    milvus_uri: str = "http://milvus:19530"
    milvus_collection: str = "gov_knowledge_v2"
    milvus_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    rag_group_enabled: bool = False
    rag_dataset_version: str = Field(
        default="none", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
    )
    rag_archive_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-fA-F]{64}$"
    )
    rag_expected_chunk_count: int = Field(default=15_858, ge=1, le=1_000_000)
    rag_expected_route_count: int = Field(default=1_012, ge=1, le=1_000_000)
    rag_group_collection_prefix: str = Field(
        default="gov_group_rag", pattern=r"^[A-Za-z][A-Za-z0-9_]{0,127}$"
    )
    rag_group_collection_alias: str = Field(
        default="gov_group_rag_active", pattern=r"^[A-Za-z][A-Za-z0-9_]{0,127}$"
    )
    rag_group_route_alias: str = Field(
        default="gov_group_rag_route_active",
        pattern=r"^[A-Za-z][A-Za-z0-9_]{0,127}$",
    )
    dashscope_api_key: SecretStr | None = None
    dashscope_api_key_file: str | None = None
    dashscope_embedding_base_url: str = (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    dashscope_embedding_model: str = "text-embedding-v4"
    dashscope_embedding_dimension: int = Field(default=1024, ge=1, le=4096)
    dashscope_embedding_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    dashscope_embedding_max_retries: int = Field(default=2, ge=0, le=5)
    rag_import_batch_size: int = Field(default=500, ge=1, le=1000)
    rag_import_batch_retries: int = Field(default=2, ge=0, le=5)

    mcp_url: str = "http://mcp-server:3000/mcp"
    mcp_health_url: str = "http://mcp-server:3000/health"
    mcp_internal_token: SecretStr = SecretStr("")
    mcp_timeout_seconds: float = Field(default=8.0, gt=0, le=60)

    mock_gov_api_url: str = "http://mock-gov-api:8080"
    dependency_health_timeout_seconds: float = Field(default=3.0, gt=0, le=30)

    llm_mode: Literal["deepseek", "stub"] = "deepseek"
    llm_model: str = "deepseek-v4-flash"
    deepseek_api_key: SecretStr | None = None
    llm_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    llm_max_retries: int = Field(default=1, ge=0, le=3)
    seed_on_startup: bool = True

    jwt_signing_key: SecretStr = SecretStr("local-demo-signing-key-change-before-deployment")
    jwt_access_minutes: int = Field(default=15, ge=1, le=1440)
    jwt_refresh_days: int = Field(default=7, ge=1, le=90)
    enable_demo_providers: bool = True
    demo_provider_ack: SecretStr | None = None
    demo_sms_code: SecretStr = SecretStr("000000")
    demo_admin_username: str = "demo_admin"
    demo_admin_password: SecretStr = SecretStr("AdminDemo!2026")
    demo_staff_username: str = "demo_staff"
    demo_staff_password: SecretStr = SecretStr("StaffDemo!2026")

    minio_endpoint: str = "http://minio:9000"
    minio_access_key: SecretStr = Field(
        default=SecretStr("minioadmin"),
        validation_alias=AliasChoices("MINIO_ACCESS_KEY", "MINIO_ROOT_USER"),
    )
    minio_secret_key: SecretStr = Field(
        default=SecretStr("minioadmin"),
        validation_alias=AliasChoices("MINIO_SECRET_KEY", "MINIO_ROOT_PASSWORD"),
    )
    materials_bucket: str = "smart-gov-materials"
    knowledge_bucket: str = "smart-gov-knowledge"
    max_material_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)

    # Asynchronous, private Word material-template generation.  It is disabled
    # by default so ordinary API replicas never perform model egress unless a
    # deployment explicitly enables the companion worker.
    material_documents_enabled: bool = False
    material_template_provider: Literal["mock", "dashscope"] = "mock"
    material_template_model: str = Field(
        default="qwen3-vl-flash-2026-01-22", min_length=1, max_length=128
    )
    material_template_dashscope_base_url: str = (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    material_template_dashscope_api_key: SecretStr | None = None
    material_template_dashscope_api_key_file: str | None = None
    material_template_manifest_path: str = (
        "resources/material_templates/v1/manifest.json"
    )
    material_template_source_prefix: str = "material-templates/v1"
    material_templates_bucket: str = "smart-gov-material-templates"
    generated_documents_bucket: str = "smart-gov-generated-documents"
    # Generated files are also covered by a one-day MinIO lifecycle rule, so
    # the API must never advertise a download window longer than the object.
    material_document_retention_hours: int = Field(default=24, ge=1, le=24)
    material_document_worker_poll_seconds: float = Field(default=1.0, ge=0.1, le=30)
    material_document_worker_lease_seconds: int = Field(default=180, ge=30, le=900)
    material_document_model_timeout_seconds: float = Field(default=90.0, ge=10, le=120)
    material_document_user_daily_limit: int = Field(default=10, ge=1, le=1000)
    material_document_user_active_limit: int = Field(default=2, ge=1, le=20)
    material_document_global_daily_limit: int = Field(default=20, ge=1, le=10_000)
    material_document_global_queue_limit: int = Field(default=50, ge=1, le=10_000)
    material_document_release_lane: str = Field(
        default="local", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )

    chat_quota_enabled: bool = False
    chat_quota_anonymous_daily: int = Field(default=10, ge=1, le=10_000)
    chat_quota_authenticated_daily: int = Field(default=30, ge=1, le=100_000)
    chat_quota_global_daily: int = Field(default=200, ge=1, le=1_000_000)
    # Optional, opaque HMAC subject hashes for explicitly authorized test
    # devices/accounts. Raw IP addresses and account identifiers never enter
    # configuration. An exempt subject bypasses both subject and global chat
    # counters; leave empty outside controlled integration testing.
    chat_quota_exempt_subject_hashes: set[str] = Field(default_factory=set)
    pii_hmac_key: SecretStr = SecretStr("local-demo-pii-hmac-change-before-deployment")

    # Huawei MetaStudio third-party-brain integration.  Production deployments
    # should mount every secret through its *_FILE setting; direct values exist
    # only to keep local unit tests and secret managers that inject environment
    # values straightforward.
    metastudio_enabled: bool = False
    metastudio_app_id: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{32}$"
    )
    metastudio_app_key: SecretStr | None = None
    metastudio_app_key_file: str | None = None
    metastudio_callback_url: str = (
        "https://123.249.68.176/api/v1/integrations/metastudio/llm"
    )
    metastudio_project_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$"
    )
    metastudio_robot_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$"
    )
    metastudio_huawei_access_key: SecretStr | None = None
    metastudio_huawei_access_key_file: str | None = None
    metastudio_huawei_secret_key: SecretStr | None = None
    metastudio_huawei_secret_key_file: str | None = None
    metastudio_region: Literal["cn-north-4"] = "cn-north-4"
    metastudio_once_code_endpoint: str = (
        "https://metastudio.cn-north-4.myhuaweicloud.com"
    )
    metastudio_server_address: str = (
        "metastudio-api.cn-north-4.myhuaweicloud.com"
    )
    metastudio_replay_window_seconds: int = Field(default=300, ge=30, le=900)
    # onceCode launch expiry is fixed at 300 seconds in the coordinator. This
    # longer Redis context survives SDK startup and the ensuing conversation.
    metastudio_context_ttl_seconds: int = Field(default=1800, ge=600, le=3600)
    metastudio_action_intent_ttl_seconds: int = Field(default=300, ge=30, le=300)
    metastudio_http_timeout_seconds: float = Field(default=10.0, gt=0, le=30)
    metastudio_session_quota_anonymous_daily: int = Field(default=5, ge=1, le=1000)
    metastudio_session_quota_authenticated_daily: int = Field(default=10, ge=1, le=1000)
    metastudio_session_quota_global_daily: int = Field(default=100, ge=1, le=100_000)
    # Camera keyframes remain opt-in. Mock is the default and performs no
    # egress; DashScope must be selected explicitly with an independent key.
    vision_enabled: bool = False
    vision_provider: Literal["mock", "dashscope"] = "mock"
    vision_dashscope_api_key: SecretStr | None = None
    vision_dashscope_api_key_file: str | None = None
    vision_dashscope_base_url: str = (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    # High-resolution document OCR is intentionally one request, but it needs
    # a longer deadline than the low-latency scene path.
    vision_document_timeout_seconds: float = Field(default=20.0, ge=5.0, le=60.0)
    vision_ticket_ttl_seconds: int = Field(default=60, ge=15, le=120)
    vision_frame_ttl_seconds: int = Field(default=30, ge=5, le=60)
    vision_fast_provider: Literal["mock", "http"] = "mock"
    vision_fast_http_url: str | None = None
    vision_fast_timeout_seconds: float = Field(default=0.5, ge=0.05, le=5.0)
    vision_fast_max_concurrency: int = Field(default=2, ge=1, le=32)
    vision_timeline_ttl_seconds: int = Field(default=120, ge=15, le=600)
    vision_timeline_max_events: int = Field(default=128, ge=8, le=1024)
    vision_sealed_turn_capacity: int = Field(default=2, ge=2, le=8)
    vision_late_memory_ttl_seconds: int = Field(default=120, ge=5, le=600)
    vision_turn_close_wait_ms: int = Field(default=2000, ge=100, le=5000)
    vision_analysis_global_daily: int = Field(default=20, ge=1, le=10_000)
    vision_max_frame_bytes: int = Field(
        default=256 * 1024, ge=16 * 1024, le=512 * 1024
    )
    vision_max_dimension: int = Field(default=1280, ge=160, le=1280)
    vision_max_sessions: int = Field(default=32, ge=1, le=256)
    vision_max_frames_per_session: int = Field(default=3, ge=1, le=3)
    vision_max_total_bytes: int = Field(
        default=8 * 1024 * 1024, ge=512 * 1024, le=64 * 1024 * 1024
    )
    vision_min_frame_interval_ms: int = Field(
        default=100, ge=0, le=5000
    )
    vision_clock_skew_seconds: int = Field(default=300, ge=30, le=900)

    @model_validator(mode="after")
    def validate_object_store_bucket_isolation(self) -> "Settings":
        """Keep the one-day generated-document lifecycle off durable buckets."""

        buckets = {
            "MATERIALS_BUCKET": self.materials_bucket,
            "KNOWLEDGE_BUCKET": self.knowledge_bucket,
            "MATERIAL_TEMPLATES_BUCKET": self.material_templates_bucket,
            "GENERATED_DOCUMENTS_BUCKET": self.generated_documents_bucket,
        }
        normalized: dict[str, str] = {}
        for name, value in buckets.items():
            candidate = value.strip().casefold()
            if not candidate:
                raise ValueError(f"{name} must not be empty")
            if candidate in normalized:
                raise ValueError(
                    f"{name} must use a dedicated bucket distinct from "
                    f"{normalized[candidate]}"
                )
            normalized[candidate] = name
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
