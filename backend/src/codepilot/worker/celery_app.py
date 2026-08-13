"""Celery application bootstrap."""

from celery import Celery

from codepilot.core.settings import Settings

DEFAULT_BROKER_URL = "redis://localhost:6379/0"
DEFAULT_RESULT_BACKEND = "redis://localhost:6379/1"
STALE_RECOVERY_TASK_NAME = "codepilot.analysis.recover_stale"


def create_celery_app(settings: Settings | None = None) -> Celery:
    """Create a Celery application from the shared settings."""
    resolved_settings = settings or Settings()
    return Celery(
        "codepilot",
        broker=resolved_settings.celery_broker_url_value(),
        backend=resolved_settings.celery_result_backend_value(),
        task_ignore_result=True,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        beat_schedule={
            "analysis-stale-recovery": {
                "task": STALE_RECOVERY_TASK_NAME,
                "schedule": resolved_settings.analysis_recovery_interval_seconds,
            }
        },
    )


celery_app = create_celery_app()

# The Docker command imports this module directly. Import task definitions here
# so a fresh worker process registers analysis tasks before consuming messages.
from codepilot.worker import analysis_tasks as _analysis_tasks  # noqa: E402,F401,RUF100
from codepilot.worker import fix_tasks as _fix_tasks  # noqa: E402,F401,RUF100
