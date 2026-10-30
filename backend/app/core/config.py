from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed configuration loaded from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = Field(default="development", description="development|ci|staging|production")
    enable_docs: bool = Field(default=True, description="Serve /docs, /redoc and openapi.json")
    docs_basic_auth_user: str | None = None
    docs_basic_auth_password: str | None = None
    frontend_origin: str = "http://localhost:8080"

    database_url: str = "postgresql+asyncpg://app_user:change-me-app@localhost:5432/taskflow"
    migration_database_url: str = (
        "postgresql+asyncpg://owner:change-me-owner@localhost:5432/taskflow"
    )
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret_key: str = "change-me-generate-a-long-random-string"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14

    rate_limit_login_per_ip: str = "10/minute"
    rate_limit_login_per_email: str = "5/15minutes"
    rate_limit_refresh_per_ip: str = "30/minute"
    rate_limit_write_per_user: str = "120/minute"
    rate_limit_read_per_user: str = "600/minute"

    email_backend: str = "console"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
