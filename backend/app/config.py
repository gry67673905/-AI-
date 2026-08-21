from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
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
    milvus_collection: str = "gov_knowledge"
    milvus_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

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


@lru_cache
def get_settings() -> Settings:
    return Settings()

