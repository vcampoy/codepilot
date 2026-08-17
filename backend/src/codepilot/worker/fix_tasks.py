"""Celery boundary for Fix Findings jobs.

The repair executor is intentionally a separate adapter. Until configured, jobs fail
closed and never publish branches or pull requests.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from uuid import UUID

from celery import Celery, Task

from codepilot.services.fix_runner import FixJobRunner
from codepilot.services.repair import (
    RepairExecutionError,
    RepairExecutor,
    RepairRequest,
    RepairResponse,
)
from codepilot.worker.celery_app import celery_app


class CeleryFixQueue:
    def enqueue(self, job_id: UUID) -> None:
        run_fix_job_task.delay(str(job_id))


def create_fix_task(
    application: Celery, runner_factory: Callable[[], FixJobRunner] | None = None
) -> Task:
    @application.task(  # type: ignore[untyped-decorator]
        bind=True, name="codepilot.fix.run", ignore_result=True
    )
    def run(self: object, job_id: str) -> None:
        async def execute() -> None:
            runner = (runner_factory or _create_default_runner)()
            await runner.run(UUID(job_id))

        asyncio.run(execute())

    return run


def _create_default_runner() -> FixJobRunner:
    """Build the production runner from worker-only runtime configuration."""
    from codepilot.core.settings import Settings
    from codepilot.github.client import GitHubAppAuthenticator, GitHubClient
    from codepilot.github.publisher import GitHubAppPullRequestPublisher
    from codepilot.repositories.analysis import PostgresAnalysisRepository
    from codepilot.repositories.fixes import PostgresFixRepository
    from codepilot.services.repair_gateway import LiteLlmRepairGateway
    from codepilot.services.sandbox import HttpSandboxVerifier

    settings = Settings()
    database_url = settings.database_url_value()
    analysis_repository = PostgresAnalysisRepository(database_url)
    fix_repository = PostgresFixRepository(database_url)
    private_key = settings.github_private_key_value()
    if (
        not settings.fix_execution_enabled
        or not settings.fix_sandbox_url
        or not settings.github_enabled
        or settings.github_app_id is None
        or not private_key
        or not settings.llm_config_encryption_key_value()
    ):
        executor = RepairExecutor(
            _UnavailableGateway(), _UnavailableSandbox(), _UnavailablePublisher()
        )
    else:
        github_client = GitHubClient(
            api_base_url=settings.github_api_base_url,
            max_retries=settings.github_max_retries,
        )
        executor = RepairExecutor(
            LiteLlmRepairGateway(
                analysis_repository,
                settings.llm_config_encryption_key_value(),
                timeout_seconds=settings.llm_timeout_seconds,
                max_tokens=settings.llm_max_tokens,
            ),
            HttpSandboxVerifier(settings.fix_sandbox_url, settings.fix_sandbox_timeout_seconds),
            GitHubAppPullRequestPublisher(
                github_client,
                GitHubAppAuthenticator(app_id=settings.github_app_id, private_key=private_key),
            ),
        )
    return FixJobRunner(analysis_repository, fix_repository, executor)


class _UnavailableGateway:
    async def generate_repair(self, _request: RepairRequest) -> RepairResponse:
        raise RepairExecutionError("Fix execution is not configured.")


class _UnavailableSandbox:
    async def verify(self, _repository_url: str, _commit_sha: str, _patch: str) -> tuple[str, ...]:
        raise RepairExecutionError("Fix execution is not configured.")


class _UnavailablePublisher:
    async def publish(
        self,
        _repository_url: str,
        _commit_sha: str,
        _branch_name: str,
        _patch: str,
        _title: str,
        _description: str,
        _base_branch: str | None = None,
    ) -> str:
        raise RepairExecutionError("Fix execution is not configured.")


run_fix_job_task = create_fix_task(celery_app)


def queue_for_celery() -> CeleryFixQueue:
    return CeleryFixQueue()
