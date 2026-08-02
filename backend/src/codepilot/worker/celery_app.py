"""Celery application bootstrap."""

import os

from celery import Celery

DEFAULT_BROKER_URL = "redis://localhost:6379/0"
DEFAULT_RESULT_BACKEND = "redis://localhost:6379/1"


def create_celery_app() -> Celery:
    """Create a Celery application from process environment configuration."""
    return Celery(
        "codepilot",
        broker=os.getenv("CELERY_BROKER_URL", DEFAULT_BROKER_URL),
        backend=os.getenv("CELERY_RESULT_BACKEND", DEFAULT_RESULT_BACKEND),
    )


celery_app = create_celery_app()
