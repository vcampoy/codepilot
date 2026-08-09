import json

import pytest
from pydantic import SecretStr, ValidationError

from codepilot.core.settings import Settings
from codepilot.worker.celery_app import create_celery_app


def test_settings_parse_environment_and_redact_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:password@db:5432/app")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173, http://localhost:4173")

    settings = Settings()

    assert settings.database_url == SecretStr("postgresql+asyncpg://user:password@db:5432/app")
    assert settings.cors_origins == ["http://localhost:5173", "http://localhost:4173"]
    assert "password" not in repr(settings)
    assert "password" not in settings.model_dump_json()


def test_settings_treats_empty_optional_environment_values_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_APP_ID", "")
    monkeypatch.setenv("GITHUB_ENABLED", "false")

    settings = Settings()

    assert settings.github_app_id is None


def test_settings_parse_llm_fallbacks_and_budgets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_FALLBACK_MODELS", "provider/backup-a, provider/backup-b")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("LLM_MAX_TOKENS", "900")

    settings = Settings()

    assert settings.llm_fallback_models == ["provider/backup-a", "provider/backup-b"]
    assert settings.llm_timeout_seconds == 45
    assert settings.llm_max_tokens == 900


def test_production_requires_github_app_credentials_when_enabled() -> None:
    with pytest.raises(ValidationError, match="github_app_id"):
        Settings(environment="production", github_enabled=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_url", "redis://db:6379/0"),
        ("redis_url", "http://redis:6379/0"),
        ("celery_broker_url", "postgresql://broker/db"),
    ],
)
def test_settings_reject_invalid_url_schemes(field: str, value: str) -> None:
    with pytest.raises(ValidationError, match=field):
        Settings(**{field: value})  # type: ignore[arg-type]


def test_production_rejects_unsafe_defaults() -> None:
    with pytest.raises(ValidationError, match="production"):
        Settings(environment="production")


def test_production_requires_complete_safe_configuration() -> None:
    settings = dict(
        environment="production",
        database_url="postgresql+asyncpg://app:strong-password@db:5432/app",
        redis_url="rediss://redis.internal:6380/0",
        celery_broker_url="rediss://redis.internal:6380/0",
        celery_result_backend="rediss://redis.internal:6380/1",
        log_format="json",
        cors_origins=["https://app.example.com"],
    )
    with pytest.raises(ValidationError, match="llm_provider"):
        Settings(**settings, llm_enabled=True)  # type: ignore[arg-type]


def test_production_requires_tls_redis_urls() -> None:
    settings = dict(
        environment="production",
        database_url="postgresql+asyncpg://app:strong-password@db:5432/app",
        redis_url="redis://redis.internal:6379/0",
        celery_broker_url="redis://redis.internal:6379/0",
        celery_result_backend="redis://redis.internal:6379/1",
        log_format="json",
        cors_origins=["https://app.example.com"],
    )

    with pytest.raises(ValidationError, match="rediss"):
        Settings(**settings)  # type: ignore[arg-type]


def test_production_validation_keeps_error_order() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(
            environment="production",
            log_format="console",
            cors_origins=["*"],
            llm_enabled=True,
        )

    message = str(error.value)
    assert message.index("auth_required") < message.index("log_format")
    assert message.index("log_format") < message.index("database_url")
    assert message.index("database_url") < message.index("cors_origins")
    assert message.index("cors_origins") < message.index("llm_provider")


def test_celery_uses_injected_settings_without_exposing_credentials() -> None:
    settings = Settings(
        celery_broker_url=SecretStr("rediss://broker.internal:6380/2"),
        celery_result_backend=SecretStr("rediss://backend.internal:6380/3"),
    )

    celery = create_celery_app(settings)

    assert celery.conf.broker_url == "rediss://broker.internal:6380/2"
    assert celery.conf.result_backend == "rediss://backend.internal:6380/3"
    assert "broker.internal" not in json.dumps(settings.model_dump(mode="json"))
