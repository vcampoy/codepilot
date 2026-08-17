"""Application service for safely queueing Fix Findings jobs."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from codepilot.domain.analysis import (
    AnalysisFinding,
    AnalysisRecord,
    AnalysisStatus,
    fingerprint_finding,
)
from codepilot.domain.fixes import FixConfiguration, FixJob, FixJobStatus, FixTargetType
from codepilot.domain.insights import FileInsight
from codepilot.domain.llm_config import LlmConfiguration
from codepilot.repositories.fixes import FixRepository


class AnalysisFixSource(Protocol):
    async def get(self, analysis_id: UUID, workspace_id: str) -> AnalysisRecord | None: ...

    async def get_llm_configuration(self, workspace_id: str) -> LlmConfiguration | None: ...

    async def get_findings(self, analysis_id: UUID) -> Sequence[AnalysisFinding]: ...

    async def get_file_insights(self, analysis_id: UUID) -> Sequence[FileInsight]: ...


class FixValidationError(ValueError):
    """The request cannot be queued under Fix Findings safety policy."""


class FixQueue(Protocol):
    def enqueue(self, job_id: UUID) -> None: ...


class FixService:
    def __init__(
        self,
        analysis_repository: AnalysisFixSource,
        repository: FixRepository,
        queue: FixQueue,
        *,
        now: Callable[[], datetime] | None = None,
        runtime_ready: Callable[[], bool] | None = None,
    ) -> None:
        self._analysis_repository = analysis_repository
        self._repository = repository
        self._queue = queue
        self._now = now or (lambda: datetime.now(UTC))
        self._runtime_ready = runtime_ready

    async def get_rules(self, workspace_id: str) -> FixConfiguration:
        return await self._repository.get_configuration(workspace_id)

    async def save_rules(self, workspace_id: str, rules: str) -> FixConfiguration:
        if len(rules) > 32_000:
            raise FixValidationError("Fix rules exceed the maximum size.")
        existing = await self._repository.get_configuration(workspace_id)
        return await self._repository.save_configuration(
            FixConfiguration(
                workspace_id,
                rules,
                self._now(),
                max_findings_per_fix=existing.max_findings_per_fix,
            )
        )

    async def save_configuration(
        self,
        workspace_id: str,
        *,
        finding_rules: str,
        hotspot_rules: str,
        max_findings_per_fix: int | None = None,
    ) -> FixConfiguration:
        if len(finding_rules) > 32_000 or len(hotspot_rules) > 32_000:
            raise FixValidationError("Fix rules exceed the maximum size.")
        current = await self._repository.get_configuration(workspace_id)
        limit = (
            max_findings_per_fix
            if max_findings_per_fix is not None
            else current.max_findings_per_fix
        )
        if not 1 <= limit <= 10:
            raise FixValidationError("Maximum findings per fix must be between 1 and 10.")
        return await self._repository.save_configuration(
            FixConfiguration(
                workspace_id,
                finding_rules,
                self._now(),
                finding_rules=finding_rules,
                hotspot_rules=hotspot_rules,
                max_findings_per_fix=limit,
            )
        )

    async def create_job(
        self,
        analysis_id: UUID,
        finding_ids: Sequence[str],
        workspace_id: str,
        *,
        target_type: FixTargetType = FixTargetType.FINDING,
    ) -> FixJob:
        if self._runtime_ready is not None and not self._runtime_ready():
            raise FixValidationError("Fix execution is not configured.")
        analysis = await self._analysis_repository.get(analysis_id, workspace_id)
        normalized = self._validate_analysis_and_ids(analysis, finding_ids, target_type)
        if analysis is None:
            raise FixValidationError("Analysis was not found.")
        await self._validate_llm(workspace_id)
        if target_type is FixTargetType.HOTSPOT:
            insights = await self._analysis_repository.get_file_insights(analysis_id)
            valid_ids = {item.path for item in insights}
        else:
            findings = await self._analysis_repository.get_findings(analysis_id)
            valid_ids = {fingerprint_finding(item) for item in findings}
            configuration = await self._repository.get_configuration(workspace_id)
            if len(normalized) > configuration.max_findings_per_fix:
                raise FixValidationError(
                    f"Select between 1 and {configuration.max_findings_per_fix} findings."
                )
        if any(item not in valid_ids for item in normalized):
            label = "hotspots" if target_type is FixTargetType.HOTSPOT else "findings"
            raise FixValidationError(f"One or more {label} were not found.")
        self._validate_github_repository(analysis)
        job = self._build_job(analysis_id, workspace_id, normalized, target_type)
        await self._repository.create_job(job)
        await self._enqueue_job(job)
        return job

    @staticmethod
    def _validate_analysis_and_ids(
        analysis: AnalysisRecord | None,
        finding_ids: Sequence[str],
        target_type: FixTargetType = FixTargetType.FINDING,
    ) -> tuple[str, ...]:
        if analysis is None:
            raise FixValidationError("Analysis was not found.")
        if analysis.status is not AnalysisStatus.COMPLETED or not analysis.commit_sha:
            raise FixValidationError("Analysis must be completed before findings can be fixed.")
        normalized = tuple(str(item).strip() for item in finding_ids)
        if any(not item for item in normalized) or len(set(normalized)) != len(normalized):
            raise FixValidationError("Target IDs must be non-empty and unique.")
        if not 1 <= len(normalized) <= 10:
            label = "hotspots" if target_type is FixTargetType.HOTSPOT else "findings"
            raise FixValidationError(f"Select between 1 and 10 {label}.")
        return normalized

    async def _validate_llm(self, workspace_id: str) -> None:
        configuration = await self._analysis_repository.get_llm_configuration(workspace_id)
        if configuration is None or not configuration.enabled:
            raise FixValidationError("LLM enrichment must be enabled before fixing findings.")

    @staticmethod
    def _validate_github_repository(analysis: AnalysisRecord) -> None:
        if urlsplit(analysis.repository_url).hostname not in {"github.com", "www.github.com"}:
            raise FixValidationError("Only GitHub repositories are supported.")

    def _build_job(
        self,
        analysis_id: UUID,
        workspace_id: str,
        finding_ids: tuple[str, ...],
        target_type: FixTargetType = FixTargetType.FINDING,
    ) -> FixJob:
        timestamp = self._now().astimezone(UTC).strftime("%Y-%m-%d-%H-%M-%S")
        now = self._now()
        job_id = uuid4()
        return FixJob(
            job_id=job_id,
            analysis_id=analysis_id,
            workspace_id=workspace_id,
            finding_ids=finding_ids if target_type is FixTargetType.FINDING else (),
            target_type=target_type,
            target_ids=finding_ids,
            branch_name=f"fix-{target_type.value}s-{timestamp}-{job_id.hex[:8]}",
            created_at=now,
            updated_at=now,
        )

    async def _enqueue_job(self, job: FixJob) -> None:
        try:
            self._queue.enqueue(job.job_id)
        except Exception as error:
            await self._repository.update_job(
                job.job_id,
                status=FixJobStatus.FAILED,
                workspace_id=job.workspace_id,
                error_message="Fix job could not be queued.",
            )
            raise RuntimeError("Fix job could not be queued.") from error

    async def get_job(self, job_id: UUID, workspace_id: str) -> FixJob:
        job = await self._repository.get_job(job_id, workspace_id)
        if job is None:
            raise FixValidationError("Fix job was not found.")
        return job
