from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
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
    llm_model: str = "deepseek-chat"
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

    chat_quota_enabled: bool = False
    chat_quota_anonymous_daily: int = Field(default=10, ge=1, le=10_000)
    chat_quota_authenticated_daily: int = Field(default=30, ge=1, le=100_000)
    chat_quota_global_daily: int = Field(default=200, ge=1, le=1_000_000)
    pii_hmac_key: SecretStr = SecretStr("local-demo-pii-hmac-change-before-deployment")


@lru_cache
def get_settings() -> Settings:
    return Settings()
