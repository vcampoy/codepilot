# ruff: noqa: E501
"""Application service for asynchronous repository analysis orchestration."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager, suppress
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import DBAPIError, OperationalError

from codepilot.analyzers.risk_score import FindingRisk, QualityGateConfig, evaluate_quality_gates
from codepilot.domain.analysis import (
    AnalysisFinding,
    AnalysisHistoryRecord,
    AnalysisNotFoundError,
    AnalysisRecord,
    AnalysisResult,
    AnalysisStatus,
    AnalysisSummary,
    InvalidAnalysisTransitionError,
    ProjectRecord,
    fingerprint_finding,
)
from codepilot.domain.insights import calculate_repository_risk, select_hotspots
from codepilot.domain.quality import QualityGatePolicy
from codepilot.repositories.analysis import AnalysisRepository
from codepilot.services.repository_ingestion import (
    RepositoryCleanupError,
    RepositoryIngestionError,
    RepositoryProcessTerminationError,
    RepositorySnapshot,
    RepositoryTimeoutError,
    RepositoryWorkspaceError,
)
from codepilot.services.source_context import enrich_findings_with_source_context

LOGGER = logging.getLogger(__name__)


class AnalysisExecutionError(Exception):
    """Base class for safe, classifiable analysis failures."""

    public_message = "Analysis could not be completed."
    retryable = False


class TransientAnalysisError(AnalysisExecutionError):
    """A failure that should be retried by the worker."""

    public_message = "Analysis is temporarily unavailable."
    retryable = True


class PermanentAnalysisError(AnalysisExecutionError):
    """A failure that must not be retried automatically."""


class NoAnalyzerExecutedError(PermanentAnalysisError):
    """No required analyzer produced executable evidence for the repository."""

    public_message = "No compatible analyzer could execute."


class AnalysisStatePersistenceError(TransientAnalysisError):
    """A failure while persisting a required retry or terminal transition."""

    def __init__(
        self,
        analysis_id: UUID,
        intended: AnalysisExecutionError,
        lease_token: UUID | None = None,
        terminalize: bool = False,
    ) -> None:
        super().__init__()
        self.analysis_id = analysis_id
        self.intended = intended
        self.lease_token = lease_token
        self.terminalize = terminalize


class AnalysisEnqueueError(Exception):
    """The queued record was created but could not be handed to Celery."""


class AnalysisDeletionConflictError(Exception):
    """An analysis cannot be deleted while it is not completed."""


class AnalysisQueue(Protocol):
    """Queue boundary that accepts identifiers only."""

    def enqueue(self, analysis_id: UUID) -> None: ...


class RepositoryIngestion(Protocol):
    """The existing Prompt 04 ingestion boundary."""

    def ingest(self, url: str) -> AbstractAsyncContextManager[RepositorySnapshot]: ...


class Analyzer(Protocol):
    """Future analyzer plugin boundary; no plugin is implemented here."""

    async def analyze(self, snapshot: RepositorySnapshot) -> AnalysisResult: ...


class NoopAnalyzer:
    """Deterministic placeholder that performs no code analysis or AI calls."""

    async def analyze(self, snapshot: RepositorySnapshot) -> AnalysisResult:
        return AnalysisResult(snapshot.file_count, 0, ())


class AnalysisService:
    """Coordinate persistence, ingestion, analyzer execution, and queueing."""

    def __init__(
        self,
        repository: AnalysisRepository,
        ingestion: RepositoryIngestion,
        analyzer: Analyzer,
        queue: AnalysisQueue,
        lease_seconds: float = 900.0,
        quality_gate_config: QualityGateConfig | None = None,
    ) -> None:
        self._repository = repository
        self._ingestion = ingestion
        self._analyzer = analyzer
        self._queue = queue
        self._lease_seconds = lease_seconds
        self._quality_gate_config = quality_gate_config or QualityGateConfig()

    async def request_analysis(
        self, repository_url: str, workspace_id: str = "default"
    ) -> AnalysisRecord:
        """Persist a queued request before publishing its identifier."""
        record = await self._repository.create(repository_url, workspace_id)
        try:
            self._queue.enqueue(record.analysis_id)
        except Exception as error:
            LOGGER.exception(
                "analysis_enqueue_failed",
                extra={"analysis_id": str(record.analysis_id)},
            )
            try:
                await self._repository.fail_queued(
                    record.analysis_id, "Analysis could not be queued."
                )
            except Exception:
                LOGGER.exception(
                    "analysis_enqueue_failure_persistence_failed",
                    extra={"analysis_id": str(record.analysis_id)},
                )
            raise AnalysisEnqueueError from error
        return record

    async def get_analysis(
        self, analysis_id: UUID, workspace_id: str | None = None
    ) -> AnalysisRecord:
        record = await self._repository.get(analysis_id, workspace_id)
        if record is None:
            raise AnalysisNotFoundError
        return record

    async def get_summary(
        self, analysis_id: UUID, workspace_id: str | None = None
    ) -> AnalysisRecord:
        return await self.get_analysis(analysis_id, workspace_id)

    async def get_findings(
        self, analysis_id: UUID, workspace_id: str | None = None
    ) -> tuple[AnalysisFinding, ...]:
        await self.get_analysis(analysis_id, workspace_id)
        return await self._repository.get_findings(analysis_id)

    async def list_projects(
        self, workspace_id: str, *, limit: int, offset: int
    ) -> tuple[tuple[ProjectRecord, ...], int]:
        return await self._repository.list_projects(workspace_id, limit=limit, offset=offset)

    async def list_project_analyses(
        self, project_id: UUID, workspace_id: str, *, limit: int, offset: int
    ) -> tuple[tuple[AnalysisRecord, ...], int]:
        return await self._repository.list_project_analyses(
            project_id, workspace_id, limit=limit, offset=offset
        )

    async def list_history(
        self, workspace_id: str, *, limit: int, offset: int
    ) -> tuple[tuple[AnalysisHistoryRecord, ...], int]:
        return await self._repository.list_history(workspace_id, limit=limit, offset=offset)

    async def delete_analysis(self, analysis_id: UUID, workspace_id: str) -> None:
        record = await self._repository.get(analysis_id, workspace_id)
        if record is None:
            raise AnalysisNotFoundError
        if record.status is not AnalysisStatus.COMPLETED:
            raise AnalysisDeletionConflictError
        await self._repository.delete_analysis(analysis_id, workspace_id)

    async def get_quality_policy(
        self, project_id: UUID, workspace_id: str
    ) -> QualityGatePolicy | None:
        return await self._repository.get_quality_policy(project_id, workspace_id)

    async def save_quality_policy(
        self, project_id: UUID, workspace_id: str, policy: QualityGatePolicy
    ) -> QualityGatePolicy:
        return await self._repository.save_quality_policy(project_id, workspace_id, policy)

    async def recover_stale_analyses(self, *, now: datetime | None = None) -> int:
        """Reclaim crashed work and republish old queued identifiers."""
        current = now or datetime.now(UTC)
        try:
            recovered = await self._repository.recover_stale_running(now=current)
            stale_ids = await self._repository.find_stale_queued(
                now=current, max_age_seconds=self._lease_seconds
            )
        except DBAPIError as error:
            raise _classify_database_error(error) from error
        republished = 0
        for analysis_id in stale_ids:
            try:
                self._queue.enqueue(analysis_id)
            except Exception:
                LOGGER.exception(
                    "analysis_orphan_republish_failed",
                    extra={"analysis_id": str(analysis_id)},
                )
            else:
                republished += 1
        return recovered + republished

    async def close(self) -> None:
        """Dispose repository resources in the event loop that owns them."""
        dispose = getattr(self._repository, "dispose", None)
        if dispose is not None:
            await dispose()

    async def process_analysis(
        self, analysis_id: UUID, *, terminalize_transient: bool = False
    ) -> None:
        """Run one idempotent delivery and persist its product state."""
        now = datetime.now(UTC)
        try:
            await self._repository.recover_stale_running(now=now)
            record = await self.get_analysis(analysis_id)
            lease_token = await self._repository.claim_running(
                record.analysis_id, now=now, lease_seconds=self._lease_seconds
            )
        except DBAPIError as error:
            raise _classify_database_error(error) from error
        if lease_token is None:
            return
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(analysis_id, lease_token))
        try:
            await self._process_claimed_analysis(
                analysis_id, record, lease_token, terminalize_transient
            )
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task

    async def _process_claimed_analysis(
        self,
        analysis_id: UUID,
        record: AnalysisRecord,
        lease_token: UUID,
        terminalize_transient: bool,
    ) -> None:
        started = time.perf_counter()
        completed = False
        try:
            async with self._ingestion.ingest(record.repository_url) as snapshot:
                result = await self._analyzer.analyze(snapshot)
                enriched_findings = await asyncio.to_thread(
                    enrich_findings_with_source_context,
                    snapshot.repository_path,
                    result.findings,
                )
                result = AnalysisResult(
                    result.analyzed_file_count,
                    result.source_lines,
                    enriched_findings,
                    result.analyzer_outcomes,
                    result.enforce_execution,
                    result.file_insights,
                )
                if result.enforce_execution and not result.execution_succeeded:
                    raise NoAnalyzerExecutedError("No required analyzer could execute.")
                await self._repository.persist_findings(
                    analysis_id, result.findings, lease_token=lease_token
                )
                await self._repository.persist_file_insights(
                    analysis_id, result.file_insights, lease_token=lease_token
                )
                stored_findings = await self._repository.get_findings(analysis_id)
                baseline = await self._repository.find_latest_completed(
                    record.repository_url,
                    record.workspace_id,
                    before=record.created_at,
                    exclude_analysis_id=analysis_id,
                )
                baseline_findings = (
                    await self._repository.get_findings(baseline.analysis_id)
                    if baseline is not None
                    else ()
                )
                get_policy = getattr(self._repository, "get_quality_policy", None)
                policy = (
                    await get_policy(record.project_id, record.workspace_id)
                    if record.project_id is not None and get_policy is not None
                    else None
                )
                summary = _build_summary(
                    result,
                    stored_findings,
                    time.perf_counter() - started,
                    quality_gate_config=policy.thresholds if policy else self._quality_gate_config,
                    quality_policy=policy,
                    baseline_analysis_id=baseline.analysis_id if baseline else None,
                    baseline_findings=baseline_findings,
                    baseline_hotspot_paths=(
                        tuple(item.path for item in select_hotspots(baseline.summary.file_insights))
                        if baseline and baseline.summary
                        else ()
                    ),
                )
                await self._repository.complete(
                    analysis_id,
                    result,
                    summary,
                    commit_sha=snapshot.commit_sha,
                    lease_token=lease_token,
                )
                completed = True
        except RepositoryCleanupError as error:
            if completed:
                LOGGER.exception(
                    "analysis_cleanup_failed_after_completion",
                    extra={"analysis_id": str(analysis_id)},
                )
                return
            classified = _classify_ingestion_error(error)
            await self._handle_failure(analysis_id, classified, lease_token, terminalize_transient)
            raise classified from error
        except InvalidAnalysisTransitionError:
            LOGGER.info(
                "analysis_delivery_lost_lease",
                extra={"analysis_id": str(analysis_id)},
            )
            return
        except AnalysisExecutionError as error:
            await self._handle_failure(analysis_id, error, lease_token, terminalize_transient)
            raise
        except RepositoryIngestionError as error:
            classified = _classify_ingestion_error(error)
            await self._handle_failure(analysis_id, classified, lease_token, terminalize_transient)
            raise classified from error
        except Exception as error:
            classified = _classify_unexpected_error(error)
            await self._handle_failure(analysis_id, classified, lease_token, terminalize_transient)
            LOGGER.exception(
                "analysis_unexpected_failure",
                extra={"analysis_id": str(analysis_id), "error_type": type(error).__name__},
            )
            raise classified from error

    async def _heartbeat_loop(self, analysis_id: UUID, lease_token: UUID) -> None:
        interval = max(self._lease_seconds / 3, 0.1)
        while True:
            await asyncio.sleep(interval)
            try:
                if not await self._repository.heartbeat(
                    analysis_id,
                    now=datetime.now(UTC),
                    lease_seconds=self._lease_seconds,
                    lease_token=lease_token,
                ):
                    return
            except Exception:
                LOGGER.exception(
                    "analysis_heartbeat_failed",
                    extra={"analysis_id": str(analysis_id)},
                )
                return

    async def mark_failed(
        self,
        analysis_id: UUID,
        error: AnalysisExecutionError,
        lease_token: UUID,
    ) -> None:
        """Persist terminal failure after the worker exhausts transient retries."""
        record = await self.get_analysis(analysis_id)
        if record.status is not AnalysisStatus.COMPLETED:
            try:
                await self._repository.fail(
                    analysis_id,
                    error.public_message,
                    retryable=False,
                    lease_token=lease_token,
                )
            except Exception as persistence_error:
                raise AnalysisStatePersistenceError(
                    analysis_id, error, lease_token
                ) from persistence_error
            return
        LOGGER.error(
            "analysis_terminal_failure_skipped_after_completion",
            extra={"analysis_id": str(analysis_id)},
        )

    async def recover_failure_state(
        self,
        analysis_id: UUID,
        error: AnalysisExecutionError,
        lease_token: UUID | None = None,
        terminalize_retryable: bool = False,
    ) -> None:
        """Retry persistence of a failure transition after a DB interruption."""
        if isinstance(error, AnalysisStatePersistenceError):
            if lease_token is None:
                lease_token = error.lease_token
            terminalize_retryable = terminalize_retryable or error.terminalize
            error = error.intended
        await self._handle_failure(analysis_id, error, lease_token, terminalize_retryable)

    async def _handle_failure(
        self,
        analysis_id: UUID,
        error: AnalysisExecutionError,
        lease_token: UUID | None = None,
        terminalize_retryable: bool = False,
    ) -> None:
        try:
            if error.retryable and not terminalize_retryable:
                await self._repository.requeue(analysis_id, lease_token=lease_token)
            else:
                await self._repository.fail(
                    analysis_id,
                    error.public_message,
                    retryable=False,
                    lease_token=lease_token,
                )
        except Exception as persistence_error:
            if isinstance(persistence_error, InvalidAnalysisTransitionError):
                LOGGER.info(
                    "analysis_failure_transition_already_owned_or_terminal",
                    extra={"analysis_id": str(analysis_id)},
                )
                return
            LOGGER.exception(
                "analysis_failure_persistence_failed",
                extra={"analysis_id": str(analysis_id)},
            )
            raise AnalysisStatePersistenceError(
                analysis_id, error, lease_token, terminalize_retryable
            ) from persistence_error
        LOGGER.exception(
            "analysis_failed",
            extra={"analysis_id": str(analysis_id), "error_type": type(error).__name__},
        )


def _build_summary(
    result: AnalysisResult,
    findings: Sequence[AnalysisFinding],
    duration_seconds: float,
    *,
    quality_gate_config: QualityGateConfig,
    quality_policy: QualityGatePolicy | None = None,
    baseline_analysis_id: UUID | None = None,
    baseline_findings: Sequence[AnalysisFinding] = (),
    baseline_hotspot_paths: Sequence[str] = (),
) -> AnalysisSummary:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    risk = calculate_repository_risk(result.file_insights) if result.file_insights else None
    hotspots = select_hotspots(result.file_insights)
    baseline_fingerprints = {fingerprint_finding(finding) for finding in baseline_findings}
    current_hotspot_paths = {item.path for item in hotspots}
    new_hotspot_count = len(current_hotspot_paths - set(baseline_hotspot_paths))
    gate = (
        evaluate_quality_gates(
            tuple(
                FindingRisk(
                    finding.path,
                    finding.severity,
                    is_new=fingerprint_finding(finding) not in baseline_fingerprints,
                    analyzer=finding.analyzer,
                    rule_id=finding.rule_id,
                )
                for finding in findings
            ),
            risk_score=risk.score if risk else 0.0,
            hotspot_count=len(hotspots),
            config=quality_gate_config,
            enabled_rules=quality_policy.enabled_rules if quality_policy else (),
            new_hotspot_count=new_hotspot_count,
        )
        if result.file_insights
        else None
    )
    return AnalysisSummary(
        analyzed_file_count=result.analyzed_file_count,
        source_lines=result.source_lines,
        finding_count_by_severity=counts,
        duration_seconds=duration_seconds,
        analyzer_outcomes=result.analyzer_outcomes,
        risk_assessment=risk,
        quality_gate=gate,
        baseline_analysis_id=baseline_analysis_id,
        file_insights=result.file_insights,
        quality_policy=quality_policy,
    )


def _classify_ingestion_error(error: RepositoryIngestionError) -> AnalysisExecutionError:
    if isinstance(
        error,
        (
            RepositoryTimeoutError,
            RepositoryWorkspaceError,
            RepositoryProcessTerminationError,
            RepositoryCleanupError,
        ),
    ):
        return TransientAnalysisError()
    return PermanentAnalysisError()


def _classify_unexpected_error(error: Exception) -> AnalysisExecutionError:
    if isinstance(error, (TimeoutError, asyncio.TimeoutError, ConnectionError)):
        return TransientAnalysisError()
    if isinstance(error, DBAPIError):
        return _classify_database_error(error)
    return PermanentAnalysisError()


def _classify_database_error(error: DBAPIError) -> AnalysisExecutionError:
    """Retry only connection/operational database failures."""
    if isinstance(error, OperationalError) or error.connection_invalidated:
        return TransientAnalysisError()
    return PermanentAnalysisError()
