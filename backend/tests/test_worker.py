import os
import subprocess  # nosec B404: fixed interpreter and test-owned command.
import sys
from pathlib import Path

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


def test_configured_celery_app_registers_analysis_task_in_fresh_process() -> None:
    backend_root = Path(__file__).parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(backend_root / "src")
    environment["DATABASE_URL"] = (
        "postgresql+asyncpg://codepilot:codepilot@localhost:5432/codepilot"
    )
    command = (
        "from codepilot.worker.celery_app import celery_app; "
        "assert 'codepilot.analysis.run' in celery_app.tasks; "
        "assert 'codepilot.analysis.recover_stale' in celery_app.tasks"
    )

    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=backend_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_worker_acknowledgement_and_periodic_recovery_configuration() -> None:
    app = create_celery_app()

    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.beat_schedule["analysis-stale-recovery"]["task"] == (
        "codepilot.analysis.recover_stale"
    )


def test_default_worker_service_is_not_cached_across_task_event_loops() -> None:
    from codepilot.worker import analysis_tasks

    first = analysis_tasks._create_default_service()
    second = analysis_tasks._create_default_service()

    assert first is not second
    assert first._repository is not second._repository
