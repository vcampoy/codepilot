"""Celery boundary for Fix Findings jobs.

The repair executor is intentionally a separate adapter. Until configured, jobs fail
closed and never publish branches or pull requests.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from celery import Celery, Task

from codepilot.domain.fixes import FixJobStatus
from codepilot.worker.celery_app import celery_app


class CeleryFixQueue:
    def enqueue(self, job_id: UUID) -> None:
        run_fix_job_task.delay(str(job_id))


def create_fix_task(application: Celery) -> Task:
    @application.task(  # type: ignore[untyped-decorator]
        bind=True, name="codepilot.fix.run", ignore_result=True
    )
    def run(self: object, job_id: str) -> None:
        asyncio.run(_fail_closed(UUID(job_id)))

    return run


async def _fail_closed(job_id: UUID) -> None:
    from codepilot.core.settings import Settings
    from codepilot.repositories.fixes import PostgresFixRepository

    repository = PostgresFixRepository(Settings().database_url_value())
    try:
        job = await repository.get_job(job_id)
        if job is not None:
            await repository.update_job(
                job_id,
                status=FixJobStatus.FAILED,
                workspace_id=job.workspace_id,
                error_message="Fix execution is not configured.",
            )
    finally:
        await repository.dispose()


run_fix_job_task = create_fix_task(celery_app)


def queue_for_celery() -> CeleryFixQueue:
    return CeleryFixQueue()
