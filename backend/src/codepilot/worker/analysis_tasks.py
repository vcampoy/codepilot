"""Celery adapter for the persisted analysis application service."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import UUID

from celery import Celery, Task
from sqlalchemy.exc import DBAPIError, OperationalError

from codepilot.services.analysis import (
    AnalysisQueue,
    AnalysisService,
    AnalysisStatePersistenceError,
    PermanentAnalysisError,
    TransientAnalysisError,
)
from codepilot.worker.celery_app import celery_app


class CeleryAnalysisQueue:
    """Publish only the persisted analysis identifier to Celery."""

    def enqueue(self, analysis_id: UUID) -> None:
        run_analysis_task.delay(str(analysis_id))


def create_analysis_task(
    application: Celery, service_factory: Callable[[], AnalysisService]
) -> Task:
    """Create a worker task whose product state remains in the repository."""

    @application.task(  # type: ignore[untyped-decorator]
        bind=True, name="codepilot.analysis.run", ignore_result=True
    )
    def run(
        self: Any,
        analysis_id: str,
        recovery: bool = False,
        lease_token: str | None = None,
        intended_retryable: bool | None = None,
        terminalize: bool = False,
    ) -> None:
        async def execute() -> None:
            service = service_factory()
            try:
                if recovery:
                    recovery_error = (
                        TransientAnalysisError()
                        if intended_retryable is not False
                        else PermanentAnalysisError()
                    )
                    await service.recover_failure_state(
                        UUID(analysis_id),
                        recovery_error,
                        UUID(lease_token) if lease_token is not None else None,
                        terminalize_retryable=terminalize,
                    )
                try:
                    await service.process_analysis(
                        UUID(analysis_id),
                        terminalize_transient=self.request.retries >= 3,
                    )
                except TransientAnalysisError:
                    if self.request.retries >= 3:
                        return
                    raise
            finally:
                await service.close()

        try:
            asyncio.run(execute())
        except AnalysisStatePersistenceError as error:
            raise self.retry(
                args=[
                    analysis_id,
                    True,
                    str(error.lease_token) if error.lease_token is not None else None,
                    error.intended.retryable,
                    error.terminalize,
                ],
                exc=error,
                countdown=5,
                max_retries=3,
            ) from error
        except TransientAnalysisError as error:
            raise self.retry(exc=error, countdown=5, max_retries=3) from error
        return None

    return run


def create_stale_recovery_task(
    application: Celery, service_factory: Callable[[], AnalysisService]
) -> Task:
    """Create the periodic task that repairs crashed and orphaned deliveries."""

    @application.task(  # type: ignore[untyped-decorator]
        bind=True, name="codepilot.analysis.recover_stale", ignore_result=True
    )
    def run(self: Any) -> None:
        async def execute() -> None:
            service = service_factory()
            try:
                await service.recover_stale_analyses()
            finally:
                await service.close()

        try:
            asyncio.run(execute())
        except TransientAnalysisError as error:
            raise self.retry(exc=error, countdown=5, max_retries=None) from error
        except (ConnectionError, TimeoutError, OperationalError) as error:
            raise self.retry(exc=error, countdown=5, max_retries=None) from error
        except DBAPIError as error:
            if error.connection_invalidated:
                raise self.retry(exc=error, countdown=5, max_retries=None) from error
            raise
        return None

    return run


def _create_default_service() -> AnalysisService:
    from codepilot.analyzers.production import ProductionRepositoryAnalyzer
    from codepilot.analyzers.risk_score import QualityGateConfig
    from codepilot.core.settings import Settings
    from codepilot.repositories.analysis import PostgresAnalysisRepository
    from codepilot.services.repository_ingestion import (
        IngestionLimits,
        RepositoryIngestionService,
    )

    settings = Settings()
    return AnalysisService(
        PostgresAnalysisRepository(settings.database_url_value()),
        RepositoryIngestionService(limits=IngestionLimits.from_settings(settings)),
        ProductionRepositoryAnalyzer(tool_timeout_seconds=settings.analysis_timeout_seconds),
        CeleryAnalysisQueue(),
        lease_seconds=settings.analysis_lease_seconds,
        quality_gate_config=QualityGateConfig(
            max_new_critical_findings=settings.quality_gate_max_new_critical_findings,
            max_risk_score=settings.quality_gate_max_risk_score,
            max_new_hotspots=settings.quality_gate_max_new_hotspots,
        ),
    )


run_analysis_task = create_analysis_task(celery_app, _create_default_service)
recover_stale_analyses_task = create_stale_recovery_task(celery_app, _create_default_service)


def queue_for_celery() -> AnalysisQueue:
    """Return the production queue boundary without exposing Celery results."""
    return CeleryAnalysisQueue()
