"""Typed application configuration."""

from functools import lru_cache
from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _validate_url(value: SecretStr, schemes: set[str], field_name: str) -> SecretStr:
    parsed = urlsplit(value.get_secret_value())
    if parsed.scheme not in schemes or not parsed.netloc:
        expected = ", ".join(sorted(schemes))
        raise ValueError(f"{field_name} must use one of: {expected}")
    return value


class Settings(BaseSettings):
    """Runtime configuration with safe development defaults."""

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
    )

    environment: Annotated[str, Field(pattern=r"^(development|test|staging|production)$")] = (
        "development"
    )
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://codepilot:codepilot@localhost:5432/codepilot"
    )
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    celery_broker_url: SecretStr = SecretStr("redis://localhost:6379/0")
    celery_result_backend: SecretStr = SecretStr("redis://localhost:6379/1")
    log_level: Annotated[str, Field(pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")] = "INFO"
    log_format: Annotated[str, Field(pattern=r"^(console|json)$")] = "console"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    repository_max_size_bytes: Annotated[int, Field(gt=0, le=10_000_000_000)] = 100_000_000
    repository_max_file_count: Annotated[int, Field(gt=0, le=1_000_000)] = 50_000
    analysis_timeout_seconds: Annotated[int, Field(gt=0, le=86_400)] = 300
    analysis_lease_seconds: Annotated[int, Field(gt=0, le=86_400)] = 900
    analysis_recovery_interval_seconds: Annotated[int, Field(gt=0, le=3_600)] = 60
    llm_enabled: bool = False
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        return _validate_url(value, {"postgresql", "postgresql+asyncpg"}, "database_url")

    @field_validator("redis_url", "celery_broker_url", "celery_result_backend")
    @classmethod
    def validate_redis_url(cls, value: SecretStr, info: Any) -> SecretStr:
        return _validate_url(value, {"redis", "rediss"}, str(info.field_name))

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def validate_production_configuration(self) -> "Settings":
        if self.environment != "production":
            return self

        errors: list[str] = []
        if self.log_format != "json":
            errors.append("log_format must be 'json' in production")
        urls = {
            "database_url": self.database_url.get_secret_value(),
            "redis_url": self.redis_url.get_secret_value(),
            "celery_broker_url": self.celery_broker_url.get_secret_value(),
            "celery_result_backend": self.celery_result_backend.get_secret_value(),
        }
        for name, value in urls.items():
            host = urlsplit(value).hostname
            if host in {"localhost", "127.0.0.1", "::1"}:
                errors.append(f"{name} must not use localhost in production")
        for name in ("redis_url", "celery_broker_url", "celery_result_backend"):
            if urlsplit(urls[name]).scheme != "rediss":
                errors.append(f"{name} must use rediss:// in production")
        database = urlsplit(self.database_url.get_secret_value())
        if database.username == "codepilot" and database.password == "codepilot":
            errors.append(
                "database_url must not use the default database credentials in production"
            )
        if (
            not self.cors_origins
            or "*" in self.cors_origins
            or any(not origin.startswith("https://") for origin in self.cors_origins)
        ):
            errors.append(
                "cors_origins must contain only HTTPS origins and must not be "
                "wildcard in production"
            )
        llm_values = (self.llm_provider, self.llm_model, self.llm_api_key_value())
        if (self.llm_enabled or any(llm_values)) and not all(llm_values):
            errors.append(
                "llm_provider, llm_model, and llm_api_key must be complete and enabled together"
            )
        if errors:
            raise ValueError("; ".join(errors))
        return self

    def database_url_value(self) -> str:
        return self.database_url.get_secret_value()

    def redis_url_value(self) -> str:
        return self.redis_url.get_secret_value()

    def celery_broker_url_value(self) -> str:
        return self.celery_broker_url.get_secret_value()

    def celery_result_backend_value(self) -> str:
        return self.celery_result_backend.get_secret_value()

    def llm_api_key_value(self) -> str | None:
        return self.llm_api_key.get_secret_value() if self.llm_api_key else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached process settings."""
    return Settings()
