import pytest

from codepilot.worker.celery_app import (
    DEFAULT_BROKER_URL,
    DEFAULT_RESULT_BACKEND,
    celery_app,
    create_celery_app,
)


def test_worker_exposes_importable_celery_application() -> None:
    assert celery_app.main == "codepilot"


def test_worker_uses_safe_local_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    monkeypatch.delenv("CELERY_RESULT_BACKEND", raising=False)

    app = create_celery_app()

    assert app.conf.broker_url == DEFAULT_BROKER_URL
    assert app.conf.result_backend == DEFAULT_RESULT_BACKEND


def test_worker_reads_environment_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://broker.example:6379/2")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://backend.example:6379/3")

    app = create_celery_app()

    assert app.conf.broker_url == "redis://broker.example:6379/2"
    assert app.conf.result_backend == "redis://backend.example:6379/3"
