"""Celery application bootstrap."""

from celery import Celery

from codepilot.core.settings import Settings

DEFAULT_BROKER_URL = "redis://localhost:6379/0"
DEFAULT_RESULT_BACKEND = "redis://localhost:6379/1"


def create_celery_app(settings: Settings | None = None) -> Celery:
    """Create a Celery application from the shared settings."""
    resolved_settings = settings or Settings()
    return Celery(
        "codepilot",
        broker=resolved_settings.celery_broker_url_value(),
        backend=resolved_settings.celery_result_backend_value(),
    )


celery_app = create_celery_app()
