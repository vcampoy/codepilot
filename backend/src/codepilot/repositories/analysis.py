# ruff: noqa: E501
"""Persistence boundary for Prompt 05 analysis state and findings."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    and_,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from codepilot.analyzers.risk_score import (
    QualityGateFailure,
    QualityGateObserved,
    QualityGateResult,
    QualityGateThresholds,
    RiskAssessment,
)
from codepilot.domain.analysis import (
    AnalysisFinding,
    AnalysisHistoryRecord,
    AnalysisNotFoundError,
    AnalysisRecord,
    AnalysisResult,
    AnalysisStatus,
    AnalysisSummary,
    AnalyzerOutcome,
    InvalidAnalysisTransitionError,
    ProjectRecord,
    SourceContext,
    SourceLine,
    fingerprint_finding,
)
from codepilot.domain.insights import FileInsight
from codepilot.domain.llm_config import LlmConfiguration
from codepilot.domain.quality import QualityGatePolicy, QualityProfile, QualityRule


class AnalysisRepository(Protocol):
    """Source-of-truth operations required by the application service."""

    async def create(
        self, repository_url: str, workspace_id: str = "default"
    ) -> AnalysisRecord: ...

    async def get_or_create_project(
        self, repository_url: str, workspace_id: str
    ) -> ProjectRecord: ...

    async def list_projects(
        self, workspace_id: str, *, limit: int, offset: int
    ) -> tuple[tuple[ProjectRecord, ...], int]: ...

    async def list_project_analyses(
        self, project_id: UUID, workspace_id: str, *, limit: int, offset: int
    ) -> tuple[tuple[AnalysisRecord, ...], int]: ...

    async def list_history(
        self, workspace_id: str, *, limit: int, offset: int
    ) -> tuple[tuple[AnalysisHistoryRecord, ...], int]: ...

    async def delete_analysis(self, analysis_id: UUID, workspace_id: str) -> None: ...

    async def get(
        self, analysis_id: UUID, workspace_id: str | None = None
    ) -> AnalysisRecord | None: ...

    async def find_latest_completed(
        self,
        repository_url: str,
        workspace_id: str,
        *,
        before: datetime,
        exclude_analysis_id: UUID,
    ) -> AnalysisRecord | None: ...

    async def claim_running(
        self,
        analysis_id: UUID,
        *,
        now: datetime | None = None,
        lease_seconds: float = 900.0,
    ) -> UUID | None: ...

    async def heartbeat(
        self,
        analysis_id: UUID,
        *,
        now: datetime,
        lease_seconds: float,
        lease_token: UUID | None = None,
    ) -> bool: ...

    async def recover_stale_running(self, *, now: datetime) -> int: ...

    async def find_stale_queued(
        self, *, now: datetime, max_age_seconds: float
    ) -> tuple[UUID, ...]: ...

    async def requeue(
        self,
        analysis_id: UUID,
        *,
        lease_token: UUID | None = None,
        now: datetime | None = None,
    ) -> None: ...

    async def persist_findings(
        self,
        analysis_id: UUID,
        findings: Sequence[AnalysisFinding],
        *,
        lease_token: UUID | None = None,
        now: datetime | None = None,
    ) -> int: ...

    async def get_findings(self, analysis_id: UUID) -> tuple[AnalysisFinding, ...]: ...

    async def persist_file_insights(
        self,
        analysis_id: UUID,
        insights: Sequence[FileInsight],
        *,
        lease_token: UUID | None = None,
        now: datetime | None = None,
    ) -> None: ...

    async def complete(
        self,
        analysis_id: UUID,
        analysis_result: AnalysisResult,
        summary: AnalysisSummary | None = None,
        *,
        commit_sha: str | None = None,
        lease_token: UUID | None = None,
        now: datetime | None = None,
    ) -> None: ...

    async def fail(
        self,
        analysis_id: UUID,
        message: str,
        *,
        retryable: bool,
        lease_token: UUID | None = None,
        now: datetime | None = None,
    ) -> None: ...

    async def fail_queued(self, analysis_id: UUID, message: str) -> None: ...

    async def get_quality_policy(
        self, project_id: UUID, workspace_id: str
    ) -> QualityGatePolicy | None: ...

    async def save_quality_policy(
        self, project_id: UUID, workspace_id: str, policy: QualityGatePolicy
    ) -> QualityGatePolicy: ...

    async def get_llm_configuration(self, workspace_id: str) -> LlmConfiguration | None: ...

    async def save_llm_configuration(self, configuration: LlmConfiguration) -> LlmConfiguration: ...


class InMemoryAnalysisRepository:
    """Small deterministic adapter for unit tests only.

    Production API and workers use :class:`PostgresAnalysisRepository`.
    """

    def __init__(self) -> None:
        self._records: dict[UUID, AnalysisRecord] = {}
        self._findings: dict[UUID, dict[str, AnalysisFinding]] = {}
        self._file_insights: dict[UUID, tuple[FileInsight, ...]] = {}
        self._lock = asyncio.Lock()
        self._projects: dict[UUID, ProjectRecord] = {}
        self._project_keys: dict[tuple[str, str], UUID] = {}
        self._quality_policies: dict[UUID, QualityGatePolicy] = {}
        self._llm_configurations: dict[str, LlmConfiguration] = {}

    async def get_llm_configuration(self, workspace_id: str) -> LlmConfiguration | None:
        async with self._lock:
            return self._llm_configurations.get(workspace_id)

    async def save_llm_configuration(self, configuration: LlmConfiguration) -> LlmConfiguration:
        async with self._lock:
            self._llm_configurations[configuration.workspace_id] = configuration
            return configuration

    async def get_quality_policy(
        self, project_id: UUID, workspace_id: str
    ) -> QualityGatePolicy | None:
        async with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.workspace_id != workspace_id:
                return None
            return self._quality_policies.get(project_id)

    async def save_quality_policy(
        self, project_id: UUID, workspace_id: str, policy: QualityGatePolicy
    ) -> QualityGatePolicy:
        async with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.workspace_id != workspace_id:
                raise KeyError("project not found")
            self._quality_policies[project_id] = policy
            return policy

    async def get_or_create_project(self, repository_url: str, workspace_id: str) -> ProjectRecord:
        key = (workspace_id, normalize_repository_url(repository_url))
        async with self._lock:
            existing = self._project_keys.get(key)
            if existing is not None:
                project = replace(self._projects[existing], updated_at=_utc_now())
                self._projects[existing] = project
                return project
            now = _utc_now()
            project = ProjectRecord(
                uuid4(),
                workspace_id,
                repository_url,
                key[1],
                repository_url.rstrip("/").split("/")[-1].removesuffix(".git") or repository_url,
                now,
                now,
            )
            self._projects[project.project_id] = project
            self._project_keys[key] = project.project_id
            return project

    async def list_projects(
        self, workspace_id: str, *, limit: int, offset: int
    ) -> tuple[tuple[ProjectRecord, ...], int]:
        async with self._lock:
            projects = sorted(
                (p for p in self._projects.values() if p.workspace_id == workspace_id),
                key=lambda item: item.updated_at,
                reverse=True,
            )
            return tuple(projects[offset : offset + limit]), len(projects)

    async def list_project_analyses(
        self, project_id: UUID, workspace_id: str, *, limit: int, offset: int
    ) -> tuple[tuple[AnalysisRecord, ...], int]:
        async with self._lock:
            records = sorted(
                (
                    r
                    for r in self._records.values()
                    if r.project_id == project_id and r.workspace_id == workspace_id
                ),
                key=lambda item: item.created_at,
                reverse=True,
            )
            return tuple(_copy_record(r) for r in records[offset : offset + limit]), len(records)

    async def list_history(
        self, workspace_id: str, *, limit: int, offset: int
    ) -> tuple[tuple[AnalysisHistoryRecord, ...], int]:
        async with self._lock:
            records = [
                record
                for record in self._records.values()
                if record.workspace_id == workspace_id
                and record.status is AnalysisStatus.COMPLETED
                and record.summary is not None
            ]
            records.sort(key=lambda item: item.created_at, reverse=True)
            items = tuple(
                _history_from_record(
                    record,
                    self._projects.get(record.project_id)
                    if record.project_id is not None
                    else None,
                )
                for record in records[offset : offset + limit]
            )
            return items, len(records)

    async def delete_analysis(self, analysis_id: UUID, workspace_id: str) -> None:
        async with self._lock:
            record = self._records.get(analysis_id)
            if record is None or record.workspace_id != workspace_id:
                raise AnalysisNotFoundError
            if record.status is not AnalysisStatus.COMPLETED:
                raise ValueError("only completed analyses can be deleted")
            del self._records[analysis_id]
            self._findings.pop(analysis_id, None)
            self._file_insights.pop(analysis_id, None)

    async def create(self, repository_url: str, workspace_id: str = "default") -> AnalysisRecord:
        async with self._lock:
            project = await self._get_or_create_project_locked(repository_url, workspace_id)
            record = AnalysisRecord(
                uuid4(),
                repository_url,
                workspace_id=workspace_id,
                project_id=project.project_id,
                created_at=_utc_now(),
            )
            self._records[record.analysis_id] = record
            self._findings[record.analysis_id] = {}
            self._file_insights[record.analysis_id] = ()
            return _copy_record(record)

    async def _get_or_create_project_locked(
        self, repository_url: str, workspace_id: str
    ) -> ProjectRecord:
        key = (workspace_id, normalize_repository_url(repository_url))
        existing = self._project_keys.get(key)
        if existing is not None:
            project = replace(self._projects[existing], updated_at=_utc_now())
            self._projects[existing] = project
            return project
        now = _utc_now()
        project = ProjectRecord(
            uuid4(),
            workspace_id,
            repository_url,
            key[1],
            repository_url.rstrip("/").split("/")[-1].removesuffix(".git") or repository_url,
            now,
            now,
        )
        self._projects[project.project_id] = project
        self._project_keys[key] = project.project_id
        return project

    async def get(
        self, analysis_id: UUID, workspace_id: str | None = None
    ) -> AnalysisRecord | None:
        async with self._lock:
            record = self._records.get(analysis_id)
            if (
                record is not None
                and workspace_id is not None
                and record.workspace_id != workspace_id
            ):
                return None
            return _copy_record(record) if record is not None else None

    async def find_latest_completed(
        self,
        repository_url: str,
        workspace_id: str,
        *,
        before: datetime,
        exclude_analysis_id: UUID,
    ) -> AnalysisRecord | None:
        async with self._lock:
            candidates = [
                record
                for record in self._records.values()
                if record.analysis_id != exclude_analysis_id
                and record.repository_url == repository_url
                and record.workspace_id == workspace_id
                and record.status is AnalysisStatus.COMPLETED
                and record.created_at < before
            ]
            latest = max(candidates, key=lambda record: record.created_at, default=None)
            return _copy_record(latest) if latest is not None else None

    async def claim_running(
        self,
        analysis_id: UUID,
        *,
        now: datetime | None = None,
        lease_seconds: float = 900.0,
    ) -> UUID | None:
        async with self._lock:
            record = self._require(analysis_id)
            if record.status is AnalysisStatus.QUEUED:
                started = now or _utc_now()
                record.status = AnalysisStatus.RUNNING
                record.failure_message = None
                record.retryable = False
                record.running_at = started
                record.lease_expires_at = started + timedelta(seconds=lease_seconds)
                token = uuid4()
                record.lease_token = token
                return token
            return None

    async def heartbeat(
        self,
        analysis_id: UUID,
        *,
        now: datetime,
        lease_seconds: float,
        lease_token: UUID | None = None,
    ) -> bool:
        async with self._lock:
            record = self._require(analysis_id)
            if (
                record.status is not AnalysisStatus.RUNNING
                or record.lease_expires_at is None
                or record.lease_expires_at <= now
                or lease_token is None
                or record.lease_token != lease_token
            ):
                return False
            record.lease_expires_at = now + timedelta(seconds=lease_seconds)
            return True

    async def recover_stale_running(self, *, now: datetime) -> int:
        async with self._lock:
            recovered = 0
            for record in self._records.values():
                if (
                    record.status is AnalysisStatus.RUNNING
                    and record.lease_expires_at is not None
                    and record.lease_expires_at <= now
                ):
                    record.status = AnalysisStatus.QUEUED
                    record.running_at = None
                    record.lease_expires_at = None
                    record.lease_token = None
                    recovered += 1
            return recovered

    async def find_stale_queued(self, *, now: datetime, max_age_seconds: float) -> tuple[UUID, ...]:
        cutoff = now - timedelta(seconds=max_age_seconds)
        async with self._lock:
            return tuple(
                record.analysis_id
                for record in self._records.values()
                if record.status is AnalysisStatus.QUEUED and record.created_at <= cutoff
            )

    async def requeue(
        self,
        analysis_id: UUID,
        *,
        lease_token: UUID | None = None,
        now: datetime | None = None,
    ) -> None:
        async with self._lock:
            record = self._require(analysis_id)
            self._require_running(record, lease_token, now)
            record.status = AnalysisStatus.QUEUED
            record.failure_message = None
            record.retryable = False
            record.running_at = None
            record.lease_expires_at = None
            record.lease_token = None

    async def persist_findings(
        self,
        analysis_id: UUID,
        findings: Sequence[AnalysisFinding],
        *,
        lease_token: UUID | None = None,
        now: datetime | None = None,
    ) -> int:
        async with self._lock:
            record = self._require(analysis_id)
            self._require_running(record, lease_token, now)
            stored = self._findings[analysis_id]
            new_count = 0
            for finding in findings:
                fingerprint = fingerprint_finding(finding)
                legacy_fingerprint = None
                if finding.analyzer != "unknown":
                    legacy_fingerprint = next(
                        (
                            key
                            for key, existing in stored.items()
                            if existing.analyzer == "unknown" and _findings_match(existing, finding)
                        ),
                        None,
                    )
                if legacy_fingerprint is not None:
                    del stored[legacy_fingerprint]
                    stored[fingerprint] = finding
                    new_count += 1
                    continue
                if fingerprint not in stored:
                    stored[fingerprint] = finding
                    new_count += 1
            return new_count

    async def get_findings(self, analysis_id: UUID) -> tuple[AnalysisFinding, ...]:
        async with self._lock:
            self._require(analysis_id)
            return tuple(self._findings[analysis_id].values())

    async def persist_file_insights(
        self,
        analysis_id: UUID,
        insights: Sequence[FileInsight],
        *,
        lease_token: UUID | None = None,
        now: datetime | None = None,
    ) -> None:
        async with self._lock:
            record = self._require(analysis_id)
            self._require_running(record, lease_token, now)
            self._file_insights[analysis_id] = tuple(insights)

    async def complete(
        self,
        analysis_id: UUID,
        analysis_result: AnalysisResult,
        summary: AnalysisSummary | None = None,
        *,
        commit_sha: str | None = None,
        lease_token: UUID | None = None,
        now: datetime | None = None,
    ) -> None:
        async with self._lock:
            record = self._require(analysis_id)
            self._require_running(record, lease_token, now)
            if summary is None:
                raise ValueError("summary is required for completion")
            record.status = AnalysisStatus.COMPLETED
            record.commit_sha = commit_sha
            record.summary = summary
            record.failure_message = None
            record.retryable = False
            record.running_at = None
            record.lease_expires_at = None
            record.lease_token = None

    async def fail(
        self,
        analysis_id: UUID,
        message: str,
        *,
        retryable: bool,
        lease_token: UUID | None = None,
        now: datetime | None = None,
    ) -> None:
        async with self._lock:
            record = self._require(analysis_id)
            if record.status not in {AnalysisStatus.QUEUED, AnalysisStatus.RUNNING}:
                raise InvalidAnalysisTransitionError(
                    f"Cannot fail analysis in {record.status.value} state."
                )
            if record.status is AnalysisStatus.RUNNING and lease_token is None:
                raise InvalidAnalysisTransitionError("Running analysis lease is required.")
            if record.status is AnalysisStatus.RUNNING:
                self._require_running(record, lease_token, now)
            if lease_token is not None and record.lease_token != lease_token:
                raise InvalidAnalysisTransitionError("Analysis lease is no longer owned.")
            record.status = AnalysisStatus.FAILED
            record.failure_message = message
            record.retryable = retryable
            record.running_at = None
            record.lease_expires_at = None
            record.lease_token = None

    async def fail_queued(self, analysis_id: UUID, message: str) -> None:
        async with self._lock:
            record = self._require(analysis_id)
            if record.status is not AnalysisStatus.QUEUED:
                raise InvalidAnalysisTransitionError(
                    f"Cannot fail analysis in {record.status.value} state."
                )
            record.status = AnalysisStatus.FAILED
            record.failure_message = message
            record.retryable = False
            record.running_at = None
            record.lease_expires_at = None
            record.lease_token = None

    def _require(self, analysis_id: UUID) -> AnalysisRecord:
        try:
            return self._records[analysis_id]
        except KeyError as error:
            raise AnalysisNotFoundError from error

    @staticmethod
    def _require_running(
        record: AnalysisRecord,
        lease_token: UUID | None = None,
        now: datetime | None = None,
    ) -> None:
        if record.status is not AnalysisStatus.RUNNING:
            raise InvalidAnalysisTransitionError(
                f"Cannot change analysis in {record.status.value} state."
            )
        if lease_token is not None and record.lease_token != lease_token:
            raise InvalidAnalysisTransitionError("Analysis lease is no longer owned.")
        if lease_token is None or record.lease_expires_at is None:
            raise InvalidAnalysisTransitionError("Analysis lease is required.")
        if record.lease_expires_at <= (now or _utc_now()):
            raise InvalidAnalysisTransitionError("Analysis lease has expired.")


def _copy_record(record: AnalysisRecord) -> AnalysisRecord:
    return AnalysisRecord(
        analysis_id=record.analysis_id,
        repository_url=record.repository_url,
        workspace_id=record.workspace_id,
        project_id=record.project_id,
        status=record.status,
        commit_sha=record.commit_sha,
        summary=record.summary,
        failure_message=record.failure_message,
        retryable=record.retryable,
        running_at=record.running_at,
        lease_expires_at=record.lease_expires_at,
        lease_token=record.lease_token,
        created_at=record.created_at,
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_repository_url(repository_url: str) -> str:
    """Normalize repository identity while preserving the original URL for display."""
    return repository_url.strip().lower().rstrip("/").removesuffix(".git")


_METADATA = MetaData()
_ANALYSES = Table(
    "codepilot_analyses",
    _METADATA,
    # PostgreSQL is the production source of truth; UUID keeps task IDs opaque.
    # SQLAlchemy's Uuid also keeps the table portable for adapter-level tests.
    Column("analysis_id", Uuid(as_uuid=True), primary_key=True),
    Column("repository_url", String(2048), nullable=False),
    Column("workspace_id", String(64), nullable=False, default="default"),
    Column("project_id", Uuid(as_uuid=True), ForeignKey("codepilot_projects.project_id")),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("status", String(16), nullable=False),
    Column("commit_sha", String(64)),
    Column("summary", JSON),
    Column("failure_message", String(512)),
    Column("retryable", Boolean, nullable=False, default=False),
    Column("running_at", DateTime(timezone=True)),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("lease_token", Uuid(as_uuid=True)),
)
_FINDINGS = Table(
    "codepilot_analysis_findings",
    _METADATA,
    Column("id", Integer, primary_key=True),
    Column(
        "analysis_id",
        Uuid(as_uuid=True),
        ForeignKey("codepilot_analyses.analysis_id"),
        nullable=False,
    ),
    Column("fingerprint", String(64), nullable=False),
    Column("path", String(2048), nullable=False),
    Column("rule_id", String(256), nullable=False),
    Column("severity", String(32), nullable=False),
    Column("message", String(4096), nullable=False),
    Column("start_line", Integer, nullable=False),
    Column("end_line", Integer, nullable=False),
    Column("analyzer", String(256), nullable=False, default="unknown"),
    Column("category", String(64), nullable=False, default="other"),
    Column("title", String(512)),
    Column("evidence", Text),
    Column("remediation", Text),
    Column("source_context", JSON),
    UniqueConstraint("analysis_id", "fingerprint", name="uq_analysis_finding_fingerprint"),
)
_PROJECTS = Table(
    "codepilot_projects",
    _METADATA,
    Column("project_id", Uuid(as_uuid=True), primary_key=True),
    Column("workspace_id", String(64), nullable=False),
    Column("repository_url", String(2048), nullable=False),
    Column("repository_key", String(2048), nullable=False),
    Column("name", String(512), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("workspace_id", "repository_key", name="uq_codepilot_project_identity"),
)
_QUALITY_POLICIES = Table(
    "codepilot_quality_policies",
    _METADATA,
    Column(
        "project_id",
        Uuid(as_uuid=True),
        ForeignKey("codepilot_projects.project_id"),
        primary_key=True,
    ),
    Column("workspace_id", String(64), nullable=False),
    Column("version", Integer, nullable=False),
    Column("payload", JSON, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
_LLM_CONFIGURATIONS = Table(
    "codepilot_llm_configurations",
    _METADATA,
    Column("workspace_id", String(64), primary_key=True),
    Column("enabled", Boolean, nullable=False),
    Column("provider", String(128), nullable=False),
    Column("model", String(256), nullable=False),
    Column("encrypted_api_key", Text),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
_FILE_INSIGHTS = Table(
    "codepilot_analysis_file_insights",
    _METADATA,
    Column(
        "analysis_id",
        Uuid(as_uuid=True),
        ForeignKey("codepilot_analyses.analysis_id"),
        nullable=False,
    ),
    Column("path", String(2048), nullable=False),
    Column("hotspot_score", Float, nullable=False),
    Column("metrics", JSON, nullable=False),
    Column("risk", JSON),
    UniqueConstraint("analysis_id", "path", name="uq_analysis_file_insight_path"),
)


class PostgresAnalysisRepository:
    """Async PostgreSQL source of truth for analysis state and findings.

    The Prompt 05 Alembic migration must run before API or worker deployment.
    This adapter intentionally does not create or mutate production schema.
    """

    def __init__(self, database_url: str, engine: AsyncEngine | None = None) -> None:
        self._engine = engine or create_async_engine(database_url, pool_pre_ping=True)

    async def get_quality_policy(
        self, project_id: UUID, workspace_id: str
    ) -> QualityGatePolicy | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(_QUALITY_POLICIES).where(
                            _QUALITY_POLICIES.c.project_id == project_id,
                            _QUALITY_POLICIES.c.workspace_id == workspace_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
        return _quality_policy_from_json(row["payload"]) if row else None

    async def save_quality_policy(
        self, project_id: UUID, workspace_id: str, policy: QualityGatePolicy
    ) -> QualityGatePolicy:
        payload = _quality_policy_to_json(policy)
        now = _utc_now()
        async with self._engine.begin() as connection:
            statement = (
                postgresql_insert(_QUALITY_POLICIES)
                .values(
                    project_id=project_id,
                    workspace_id=workspace_id,
                    version=policy.version,
                    payload=payload,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=[_QUALITY_POLICIES.c.project_id],
                    set_={
                        "workspace_id": workspace_id,
                        "version": policy.version,
                        "payload": payload,
                        "updated_at": now,
                    },
                )
            )
            await connection.execute(statement)
        return policy

    async def get_llm_configuration(self, workspace_id: str) -> LlmConfiguration | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(_LLM_CONFIGURATIONS).where(
                            _LLM_CONFIGURATIONS.c.workspace_id == workspace_id
                        )
                    )
                )
                .mappings()
                .first()
            )
        return _llm_configuration_from_row(row) if row else None

    async def save_llm_configuration(self, configuration: LlmConfiguration) -> LlmConfiguration:
        async with self._engine.begin() as connection:
            statement = (
                postgresql_insert(_LLM_CONFIGURATIONS)
                .values(
                    workspace_id=configuration.workspace_id,
                    enabled=configuration.enabled,
                    provider=configuration.provider,
                    model=configuration.model,
                    encrypted_api_key=configuration.encrypted_api_key,
                    updated_at=configuration.updated_at,
                )
                .on_conflict_do_update(
                    index_elements=[_LLM_CONFIGURATIONS.c.workspace_id],
                    set_={
                        "enabled": configuration.enabled,
                        "provider": configuration.provider,
                        "model": configuration.model,
                        "encrypted_api_key": configuration.encrypted_api_key,
                        "updated_at": configuration.updated_at,
                    },
                )
            )
            await connection.execute(statement)
        return configuration

    async def get_or_create_project(self, repository_url: str, workspace_id: str) -> ProjectRecord:
        key = normalize_repository_url(repository_url)
        now = _utc_now()
        name = repository_url.rstrip("/").split("/")[-1].removesuffix(".git") or repository_url
        async with self._engine.begin() as connection:
            project_id = uuid4()
            statement = (
                postgresql_insert(_PROJECTS)
                .values(
                    project_id=project_id,
                    workspace_id=workspace_id,
                    repository_url=repository_url,
                    repository_key=key,
                    name=name,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=[_PROJECTS.c.workspace_id, _PROJECTS.c.repository_key],
                    set_={"repository_url": repository_url, "name": name, "updated_at": now},
                )
                .returning(*_PROJECTS.c)
            )
            row = (await connection.execute(statement)).mappings().one()
        return _project_from_row(row)

    async def list_projects(
        self, workspace_id: str, *, limit: int, offset: int
    ) -> tuple[tuple[ProjectRecord, ...], int]:
        async with self._engine.connect() as connection:
            count = int(
                (
                    await connection.execute(
                        select(func.count())
                        .select_from(_PROJECTS)
                        .where(_PROJECTS.c.workspace_id == workspace_id)
                    )
                ).scalar_one()
            )
            result = await connection.execute(
                select(_PROJECTS)
                .where(_PROJECTS.c.workspace_id == workspace_id)
                .order_by(_PROJECTS.c.updated_at.desc())
                .offset(offset)
                .limit(limit)
            )
            rows = result.mappings().all()
        return tuple(_project_from_row(row) for row in rows), count

    async def list_project_analyses(
        self, project_id: UUID, workspace_id: str, *, limit: int, offset: int
    ) -> tuple[tuple[AnalysisRecord, ...], int]:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                select(_ANALYSES)
                .where(
                    _ANALYSES.c.project_id == project_id, _ANALYSES.c.workspace_id == workspace_id
                )
                .order_by(_ANALYSES.c.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            rows = result.mappings().all()
            count = int(
                (
                    await connection.execute(
                        select(func.count())
                        .select_from(_ANALYSES)
                        .where(
                            _ANALYSES.c.project_id == project_id,
                            _ANALYSES.c.workspace_id == workspace_id,
                        )
                    )
                ).scalar_one()
            )
        return tuple(_record_from_row(row) for row in rows), count

    async def list_history(
        self, workspace_id: str, *, limit: int, offset: int
    ) -> tuple[tuple[AnalysisHistoryRecord, ...], int]:
        # Summary JSON is already the aggregate source of truth. Decode each row in Python
        # so PostgreSQL JSON operator differences cannot alter the public contract.
        async with self._engine.connect() as connection:
            count = int(
                (
                    await connection.execute(
                        select(func.count())
                        .select_from(_ANALYSES)
                        .where(
                            _ANALYSES.c.workspace_id == workspace_id,
                            _ANALYSES.c.status == AnalysisStatus.COMPLETED.value,
                            _ANALYSES.c.summary.is_not(None),
                        )
                    )
                ).scalar_one()
            )
            result = await connection.execute(
                select(_ANALYSES, _PROJECTS.c.name.label("repository_name"))
                .select_from(
                    _ANALYSES.outerjoin(_PROJECTS, _ANALYSES.c.project_id == _PROJECTS.c.project_id)
                )
                .where(
                    _ANALYSES.c.workspace_id == workspace_id,
                    _ANALYSES.c.status == AnalysisStatus.COMPLETED.value,
                    _ANALYSES.c.summary.is_not(None),
                )
                .order_by(_ANALYSES.c.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            rows = result.mappings().all()
        return tuple(_history_from_row(row) for row in rows), count

    async def delete_analysis(self, analysis_id: UUID, workspace_id: str) -> None:
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    select(_ANALYSES.c.status).where(
                        _ANALYSES.c.analysis_id == analysis_id,
                        _ANALYSES.c.workspace_id == workspace_id,
                    )
                )
            ).one_or_none()
            if row is None:
                raise AnalysisNotFoundError
            if row[0] != AnalysisStatus.COMPLETED.value:
                raise ValueError("only completed analyses can be deleted")
            await connection.execute(
                _FILE_INSIGHTS.delete().where(_FILE_INSIGHTS.c.analysis_id == analysis_id)
            )
            await connection.execute(
                _FINDINGS.delete().where(_FINDINGS.c.analysis_id == analysis_id)
            )
            await connection.execute(
                _ANALYSES.delete().where(
                    _ANALYSES.c.analysis_id == analysis_id,
                    _ANALYSES.c.workspace_id == workspace_id,
                )
            )

    async def create(self, repository_url: str, workspace_id: str = "default") -> AnalysisRecord:
        project = await self.get_or_create_project(repository_url, workspace_id)
        record = AnalysisRecord(
            uuid4(),
            repository_url,
            workspace_id=workspace_id,
            project_id=project.project_id,
            created_at=_utc_now(),
        )
        async with self._engine.begin() as connection:
            await connection.execute(
                insert(_ANALYSES).values(
                    analysis_id=record.analysis_id,
                    repository_url=record.repository_url,
                    workspace_id=record.workspace_id,
                    project_id=record.project_id,
                    created_at=record.created_at,
                    status=record.status.value,
                    retryable=False,
                )
            )
        return record

    async def get(
        self, analysis_id: UUID, workspace_id: str | None = None
    ) -> AnalysisRecord | None:
        async with self._engine.connect() as connection:
            conditions = [_ANALYSES.c.analysis_id == analysis_id]
            if workspace_id is not None:
                conditions.append(_ANALYSES.c.workspace_id == workspace_id)
            result = await connection.execute(select(_ANALYSES).where(and_(*conditions)))
            row = result.mappings().one_or_none()
        return _record_from_row(row) if row is not None else None

    async def find_latest_completed(
        self,
        repository_url: str,
        workspace_id: str,
        *,
        before: datetime,
        exclude_analysis_id: UUID,
    ) -> AnalysisRecord | None:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                select(_ANALYSES)
                .where(
                    _ANALYSES.c.repository_url == repository_url,
                    _ANALYSES.c.workspace_id == workspace_id,
                    _ANALYSES.c.status == AnalysisStatus.COMPLETED.value,
                    _ANALYSES.c.created_at < before,
                    _ANALYSES.c.analysis_id != exclude_analysis_id,
                )
                .order_by(_ANALYSES.c.created_at.desc())
                .limit(1)
            )
            row = result.mappings().one_or_none()
        return _record_from_row(row) if row is not None else None

    async def claim_running(
        self,
        analysis_id: UUID,
        *,
        now: datetime | None = None,
        lease_seconds: float = 900.0,
    ) -> UUID | None:
        started = now or _utc_now()
        lease_token = uuid4()
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(_ANALYSES)
                .where(
                    _ANALYSES.c.analysis_id == analysis_id,
                    _ANALYSES.c.status == AnalysisStatus.QUEUED.value,
                )
                .values(
                    status=AnalysisStatus.RUNNING.value,
                    retryable=False,
                    running_at=started,
                    lease_expires_at=started + timedelta(seconds=lease_seconds),
                    lease_token=lease_token,
                )
            )
            claimed = result.rowcount == 1
        if claimed:
            return lease_token
        record = await self.get(analysis_id)
        if record is None:
            raise AnalysisNotFoundError
        return None

    async def heartbeat(
        self,
        analysis_id: UUID,
        *,
        now: datetime,
        lease_seconds: float,
        lease_token: UUID | None = None,
    ) -> bool:
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(_ANALYSES)
                .where(
                    _ANALYSES.c.analysis_id == analysis_id,
                    _ANALYSES.c.status == AnalysisStatus.RUNNING.value,
                    _ANALYSES.c.lease_expires_at > now,
                    _ANALYSES.c.lease_token == lease_token,
                )
                .values(lease_expires_at=now + timedelta(seconds=lease_seconds))
            )
        if result.rowcount:
            return True
        record = await self.get(analysis_id)
        if record is None:
            raise AnalysisNotFoundError
        return False

    async def recover_stale_running(self, *, now: datetime) -> int:
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(_ANALYSES)
                .where(
                    _ANALYSES.c.status == AnalysisStatus.RUNNING.value,
                    _ANALYSES.c.lease_expires_at <= now,
                )
                .values(
                    status=AnalysisStatus.QUEUED.value,
                    running_at=None,
                    lease_expires_at=None,
                    failure_message=None,
                    retryable=False,
                    lease_token=None,
                )
            )
        return result.rowcount

    async def find_stale_queued(self, *, now: datetime, max_age_seconds: float) -> tuple[UUID, ...]:
        cutoff = now - timedelta(seconds=max_age_seconds)
        async with self._engine.connect() as connection:
            result = await connection.execute(
                select(_ANALYSES.c.analysis_id).where(
                    _ANALYSES.c.status == AnalysisStatus.QUEUED.value,
                    _ANALYSES.c.created_at <= cutoff,
                )
            )
            rows = result.all()
        return tuple(cast(UUID, row[0]) for row in rows)

    async def requeue(
        self,
        analysis_id: UUID,
        *,
        lease_token: UUID | None = None,
        now: datetime | None = None,
    ) -> None:
        current = now or _utc_now()
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(_ANALYSES)
                .where(
                    _ANALYSES.c.analysis_id == analysis_id,
                    _ANALYSES.c.status == AnalysisStatus.RUNNING.value,
                    _ANALYSES.c.lease_token == lease_token,
                    _ANALYSES.c.lease_expires_at > current,
                )
                .values(
                    status=AnalysisStatus.QUEUED.value,
                    failure_message=None,
                    retryable=False,
                    running_at=None,
                    lease_expires_at=None,
                    lease_token=None,
                )
            )
        if result.rowcount != 1:
            await self._raise_for_invalid_transition(
                analysis_id, lease_token=lease_token, now=current
            )

    async def persist_findings(
        self,
        analysis_id: UUID,
        findings: Sequence[AnalysisFinding],
        *,
        lease_token: UUID | None = None,
        now: datetime | None = None,
    ) -> int:
        values: list[dict[str, object]] = [
            {
                "analysis_id": analysis_id,
                "fingerprint": fingerprint_finding(finding),
                "path": finding.path,
                "rule_id": finding.rule_id,
                "severity": finding.severity,
                "message": finding.message,
                "start_line": finding.start_line,
                "end_line": finding.end_line,
                "analyzer": finding.analyzer,
                "category": finding.category,
                "title": finding.title,
                "evidence": finding.evidence,
                "remediation": finding.remediation,
                "source_context": _source_context_to_json(finding.source_context),
            }
            for finding in findings
        ]
        async with self._engine.begin() as connection:
            await self._require_running(connection, analysis_id, lease_token, now)
            if not values:
                return 0
            legacy_result = await connection.execute(
                select(_FINDINGS).where(
                    _FINDINGS.c.analysis_id == analysis_id,
                    _FINDINGS.c.analyzer == "unknown",
                )
            )
            legacy_rows = [
                (_finding_from_row(row), row["id"]) for row in legacy_result.mappings().all()
            ]
            upgraded = 0
            insert_values: list[dict[str, object]] = []
            for value, finding in zip(values, findings, strict=True):
                legacy_index = next(
                    (
                        index
                        for index, (legacy, _) in enumerate(legacy_rows)
                        if _findings_match(legacy, finding)
                    ),
                    None,
                )
                if legacy_index is None:
                    insert_values.append(value)
                    continue
                _, legacy_id = legacy_rows.pop(legacy_index)
                await connection.execute(
                    update(_FINDINGS)
                    .where(_FINDINGS.c.id == legacy_id)
                    .values(
                        analyzer=finding.analyzer,
                        fingerprint=value["fingerprint"],
                        title=value["title"],
                        evidence=value["evidence"],
                        remediation=value["remediation"],
                        source_context=value["source_context"],
                    )
                )
                upgraded += 1
            if not insert_values:
                return upgraded
            statement = postgresql_insert(_FINDINGS).values(insert_values)
            statement = statement.on_conflict_do_nothing(
                index_elements=[_FINDINGS.c.analysis_id, _FINDINGS.c.fingerprint]
            )
            result = await connection.execute(statement)
            return upgraded + result.rowcount

    async def get_findings(self, analysis_id: UUID) -> tuple[AnalysisFinding, ...]:
        async with self._engine.connect() as connection:
            await self._require_running_or_terminal(connection, analysis_id)
            result = await connection.execute(
                select(_FINDINGS)
                .where(_FINDINGS.c.analysis_id == analysis_id)
                .order_by(_FINDINGS.c.id)
            )
            rows = result.mappings().all()
        return tuple(_finding_from_row(row) for row in rows)

    async def persist_file_insights(
        self,
        analysis_id: UUID,
        insights: Sequence[FileInsight],
        *,
        lease_token: UUID | None = None,
        now: datetime | None = None,
    ) -> None:
        values = [
            {
                "analysis_id": analysis_id,
                "path": insight.path,
                "hotspot_score": insight.hotspot_score,
                "metrics": insight.metrics,
                "risk": _risk_to_json(insight.risk) if insight.risk else None,
            }
            for insight in insights
        ]
        async with self._engine.begin() as connection:
            await self._require_running(connection, analysis_id, lease_token, now)
            await connection.execute(
                _FILE_INSIGHTS.delete().where(_FILE_INSIGHTS.c.analysis_id == analysis_id)
            )
            if values:
                await connection.execute(_FILE_INSIGHTS.insert(), values)

    async def complete(
        self,
        analysis_id: UUID,
        analysis_result: AnalysisResult,
        summary: AnalysisSummary | None = None,
        *,
        commit_sha: str | None = None,
        lease_token: UUID | None = None,
        now: datetime | None = None,
    ) -> None:
        del analysis_result
        if summary is None:
            raise ValueError("summary is required for completion")
        current = now or _utc_now()
        async with self._engine.begin() as connection:
            update_result = await connection.execute(
                update(_ANALYSES)
                .where(
                    _ANALYSES.c.analysis_id == analysis_id,
                    _ANALYSES.c.status == AnalysisStatus.RUNNING.value,
                    _ANALYSES.c.lease_token == lease_token,
                    _ANALYSES.c.lease_expires_at > current,
                )
                .values(
                    status=AnalysisStatus.COMPLETED.value,
                    commit_sha=commit_sha,
                    summary=_summary_to_json(summary),
                    failure_message=None,
                    retryable=False,
                    running_at=None,
                    lease_expires_at=None,
                    lease_token=None,
                )
            )
        if update_result.rowcount != 1:
            await self._raise_for_invalid_transition(
                analysis_id, lease_token=lease_token, now=current
            )

    async def fail(
        self,
        analysis_id: UUID,
        message: str,
        *,
        retryable: bool,
        lease_token: UUID | None = None,
        now: datetime | None = None,
    ) -> None:
        current = now or _utc_now()
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(_ANALYSES)
                .where(
                    _ANALYSES.c.analysis_id == analysis_id,
                    (
                        _ANALYSES.c.status == AnalysisStatus.QUEUED.value
                        if lease_token is None
                        else or_(
                            _ANALYSES.c.status == AnalysisStatus.QUEUED.value,
                            and_(
                                _ANALYSES.c.status == AnalysisStatus.RUNNING.value,
                                _ANALYSES.c.lease_token == lease_token,
                                _ANALYSES.c.lease_expires_at > current,
                            ),
                        )
                    ),
                )
                .values(
                    status=AnalysisStatus.FAILED.value,
                    failure_message=message,
                    retryable=retryable,
                    running_at=None,
                    lease_expires_at=None,
                    lease_token=None,
                )
            )
        if result.rowcount != 1:
            await self._raise_for_invalid_transition(
                analysis_id, lease_token=lease_token, now=current
            )

    async def fail_queued(self, analysis_id: UUID, message: str) -> None:
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(_ANALYSES)
                .where(
                    _ANALYSES.c.analysis_id == analysis_id,
                    _ANALYSES.c.status == AnalysisStatus.QUEUED.value,
                )
                .values(
                    status=AnalysisStatus.FAILED.value,
                    failure_message=message,
                    retryable=False,
                    running_at=None,
                    lease_expires_at=None,
                    lease_token=None,
                )
            )
        if result.rowcount != 1:
            await self._raise_for_invalid_transition(analysis_id)

    async def dispose(self) -> None:
        await self._engine.dispose()

    async def _require_running(
        self,
        connection: Any,
        analysis_id: UUID,
        lease_token: UUID | None = None,
        now: datetime | None = None,
    ) -> None:
        result = await connection.execute(
            select(
                _ANALYSES.c.status,
                _ANALYSES.c.lease_token,
                _ANALYSES.c.lease_expires_at,
            )
            .where(_ANALYSES.c.analysis_id == analysis_id)
            .with_for_update()
        )
        row = result.one_or_none()
        if row is None:
            raise AnalysisNotFoundError
        if row[0] != AnalysisStatus.RUNNING.value:
            raise InvalidAnalysisTransitionError(f"Cannot change analysis in {row[0]} state.")
        if lease_token is not None and row[1] != lease_token:
            raise InvalidAnalysisTransitionError("Analysis lease is no longer owned.")
        if lease_token is None or row[2] is None:
            raise InvalidAnalysisTransitionError("Analysis lease is required.")
        if cast(datetime, row[2]) <= (now or _utc_now()):
            raise InvalidAnalysisTransitionError("Analysis lease has expired.")

    async def _require_running_or_terminal(self, connection: Any, analysis_id: UUID) -> None:
        result = await connection.execute(
            select(_ANALYSES.c.analysis_id).where(_ANALYSES.c.analysis_id == analysis_id)
        )
        if result.one_or_none() is None:
            raise AnalysisNotFoundError

    async def _raise_for_invalid_transition(
        self,
        analysis_id: UUID,
        *,
        lease_token: UUID | None = None,
        now: datetime | None = None,
    ) -> None:
        record = await self.get(analysis_id)
        if record is None:
            raise AnalysisNotFoundError
        if record.status is AnalysisStatus.RUNNING and (
            lease_token is None
            or record.lease_token != lease_token
            or record.lease_expires_at is None
            or record.lease_expires_at <= (now or _utc_now())
        ):
            raise InvalidAnalysisTransitionError("Analysis lease is no longer valid.")
        raise InvalidAnalysisTransitionError(
            f"Cannot change analysis in {record.status.value} state."
        )


def _record_from_row(row: Any) -> AnalysisRecord:
    summary = row["summary"]
    return AnalysisRecord(
        analysis_id=cast(UUID, row["analysis_id"]),
        repository_url=cast(str, row["repository_url"]),
        workspace_id=cast(str, row["workspace_id"]),
        project_id=cast(UUID | None, row.get("project_id")),
        status=AnalysisStatus(cast(str, row["status"])),
        commit_sha=cast(str | None, row["commit_sha"]),
        summary=_summary_from_json(summary),
        failure_message=cast(str | None, row["failure_message"]),
        retryable=bool(row["retryable"]),
        running_at=cast(datetime | None, row["running_at"]),
        lease_expires_at=cast(datetime | None, row["lease_expires_at"]),
        lease_token=cast(UUID | None, row["lease_token"]),
        created_at=cast(datetime, row["created_at"]),
    )


def _finding_from_row(row: Any) -> AnalysisFinding:
    return AnalysisFinding(
        path=cast(str, row["path"]),
        rule_id=cast(str, row["rule_id"]),
        severity=cast(str, row["severity"]),
        message=cast(str, row["message"]),
        start_line=int(row["start_line"]),
        end_line=int(row["end_line"]),
        analyzer=cast(str, row.get("analyzer", "unknown")),
        category=cast(str, row.get("category", "other")),
        title=cast(str | None, row.get("title")),
        evidence=cast(str | None, row.get("evidence")),
        remediation=cast(str | None, row.get("remediation")),
        source_context=_source_context_from_json(row.get("source_context")),
    )


def _project_from_row(row: Any) -> ProjectRecord:
    return ProjectRecord(
        project_id=cast(UUID, row["project_id"]),
        workspace_id=cast(str, row["workspace_id"]),
        repository_url=cast(str, row["repository_url"]),
        repository_key=cast(str, row["repository_key"]),
        name=cast(str, row["name"]),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
    )


def _quality_policy_to_json(policy: QualityGatePolicy) -> dict[str, Any]:
    return {
        "version": policy.version,
        "thresholds": {
            "max_new_critical_findings": policy.thresholds.max_new_critical_findings,
            "max_risk_score": policy.thresholds.max_risk_score,
            "max_new_hotspots": policy.thresholds.max_new_hotspots,
        },
        "profiles": [
            {
                "language": profile.language,
                "rules": [
                    {
                        "language": rule.language,
                        "analyzer": rule.analyzer,
                        "rule_id": rule.rule_id,
                        "enabled": rule.enabled,
                    }
                    for rule in profile.rules
                ],
            }
            for profile in policy.profiles
        ],
    }


def _quality_policy_from_json(value: Any) -> QualityGatePolicy:
    payload = value if isinstance(value, dict) else {}
    thresholds = payload.get("thresholds", {})
    profiles = tuple(
        QualityProfile(
            str(item.get("language", "unknown")),
            tuple(
                QualityRule(
                    str(rule.get("language", item.get("language", "unknown"))),
                    str(rule.get("analyzer", "")),
                    str(rule.get("rule_id", "")),
                    bool(rule.get("enabled", True)),
                )
                for rule in item.get("rules", [])
            ),
        )
        for item in payload.get("profiles", [])
        if isinstance(item, dict)
    )
    from codepilot.analyzers.risk_score import QualityGateConfig

    return QualityGatePolicy(
        version=int(payload.get("version", 1)),
        thresholds=QualityGateConfig(
            max_new_critical_findings=_optional_int(thresholds.get("max_new_critical_findings")),
            max_risk_score=_optional_float(thresholds.get("max_risk_score")),
            max_new_hotspots=_optional_int(thresholds.get("max_new_hotspots")),
        ),
        profiles=profiles,
    )


def _source_context_to_json(context: SourceContext | None) -> dict[str, object] | None:
    if context is None:
        return None
    return {
        "start_line": context.start_line,
        "end_line": context.end_line,
        "lines": [
            {"number": line.number, "text": line.text, "highlighted": line.highlighted}
            for line in context.lines
        ],
    }


def _source_context_from_json(value: Any) -> SourceContext | None:
    if not isinstance(value, dict):
        return None
    try:
        return SourceContext(
            start_line=int(value["start_line"]),
            end_line=int(value["end_line"]),
            lines=tuple(
                SourceLine(
                    number=int(item["number"]),
                    text=str(item["text"]),
                    highlighted=bool(item.get("highlighted", False)),
                )
                for item in value.get("lines", [])
            ),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _finding_identity(finding: AnalysisFinding) -> tuple[object, ...]:
    """Identity used to upgrade findings persisted before analyzer provenance existed."""
    return (
        finding.path,
        finding.rule_id,
        finding.severity,
        finding.message,
        finding.start_line,
        finding.end_line,
    )


def _findings_match(left: AnalysisFinding, right: AnalysisFinding) -> bool:
    return _finding_identity(left)[1:] == _finding_identity(right)[1:] and _paths_match(
        left.path, right.path
    )


def _paths_match(left: str, right: str) -> bool:
    left_value = left.replace("\\", "/")
    right_value = right.replace("\\", "/")
    if left_value == right_value:
        return True
    if left_value.startswith("/"):
        return left_value.endswith("/" + right_value.lstrip("/"))
    if right_value.startswith("/"):
        return right_value.endswith("/" + left_value.lstrip("/"))
    return False


def _summary_to_json(summary: AnalysisSummary) -> dict[str, object]:
    payload = _summary_base_to_json(summary)
    payload.update(_summary_optional_to_json(summary))
    return payload


def _summary_base_to_json(summary: AnalysisSummary) -> dict[str, object]:
    return {
        "analyzed_file_count": summary.analyzed_file_count,
        "source_lines": summary.source_lines,
        "finding_count_by_severity": summary.finding_count_by_severity,
        "duration_seconds": summary.duration_seconds,
        "analyzer_outcomes": [
            _analyzer_outcome_to_json(item) for item in summary.analyzer_outcomes
        ],
    }


def _analyzer_outcome_to_json(item: AnalyzerOutcome) -> dict[str, object]:
    return {
        "analyzer": item.analyzer,
        "tool": item.tool,
        "version": item.version,
        "status": item.status,
        "duration_seconds": item.duration_seconds,
        "message": item.message,
        "language": item.language,
        "generic": item.generic,
    }


def _summary_optional_to_json(summary: AnalysisSummary) -> dict[str, object]:
    payload: dict[str, object] = {}
    if summary.risk_assessment is not None:
        payload["risk_assessment"] = _risk_to_json(summary.risk_assessment)
    if summary.quality_gate is not None:
        payload["quality_gate"] = _quality_gate_to_json(summary.quality_gate)
    if summary.baseline_analysis_id is not None:
        payload["baseline_analysis_id"] = str(summary.baseline_analysis_id)
    if summary.quality_policy is not None:
        payload["quality_policy"] = _quality_policy_to_json(summary.quality_policy)
    if summary.file_insights:
        payload["file_insights"] = [_file_insight_to_json(item) for item in summary.file_insights]
    return payload


def _quality_gate_to_json(gate: QualityGateResult) -> dict[str, object]:
    return {
        "passed": gate.passed,
        "configured": gate.configured,
        "failures": [{"code": item.code, "detail": item.detail} for item in gate.failures],
        "thresholds": {
            "max_new_critical_findings": gate.thresholds.max_new_critical_findings,
            "max_risk_score": gate.thresholds.max_risk_score,
            "max_new_hotspots": gate.thresholds.max_new_hotspots,
        },
        "observed": {
            "new_critical_findings": gate.observed.new_critical_findings,
            "risk_score": gate.observed.risk_score,
            "new_hotspots": gate.observed.new_hotspots,
        },
    }


def _file_insight_to_json(insight: FileInsight) -> dict[str, object]:
    return {
        "path": insight.path,
        "hotspot_score": insight.hotspot_score,
        "metrics": insight.metrics,
        "risk": _risk_to_json(insight.risk) if insight.risk else None,
    }


def _summary_from_json(value: Any) -> AnalysisSummary | None:
    if value is None:
        return None
    return AnalysisSummary(
        analyzed_file_count=int(value["analyzed_file_count"]),
        source_lines=int(value["source_lines"]),
        finding_count_by_severity=_finding_counts_from_json(value),
        duration_seconds=float(value["duration_seconds"]),
        analyzer_outcomes=_analyzer_outcomes_from_json(value),
        risk_assessment=_risk_from_json(value.get("risk_assessment")),
        quality_gate=_quality_gate_from_json(value.get("quality_gate")),
        baseline_analysis_id=_baseline_id_from_json(value),
        file_insights=_file_insights_from_json(value),
        quality_policy=_quality_policy_from_summary_json(value),
    )


def _finding_counts_from_json(value: dict[str, Any]) -> dict[str, int]:
    return {str(key): int(count) for key, count in dict(value["finding_count_by_severity"]).items()}


def _analyzer_outcomes_from_json(value: dict[str, Any]) -> tuple[AnalyzerOutcome, ...]:
    return tuple(
        AnalyzerOutcome(
            analyzer=str(item["analyzer"]),
            tool=str(item.get("tool", item["analyzer"])),
            version=item.get("version"),
            status=str(item.get("status", "succeeded")),
            duration_seconds=float(item.get("duration_seconds", 0.0)),
            message=item.get("message"),
            language=item.get("language"),
            generic=bool(item.get("generic", False)),
        )
        for item in value.get("analyzer_outcomes", [])
    )


def _quality_gate_from_json(value: Any) -> QualityGateResult | None:
    if value is None:
        return None
    thresholds = value.get("thresholds", {})
    observed = value.get("observed", {})
    return QualityGateResult(
        bool(value.get("passed")),
        tuple(
            QualityGateFailure(str(item["code"]), str(item["detail"]))
            for item in value.get("failures", [])
        ),
        bool(value.get("configured", True)),
        thresholds=QualityGateThresholds(
            max_new_critical_findings=_optional_int(thresholds.get("max_new_critical_findings")),
            max_risk_score=_optional_float(thresholds.get("max_risk_score")),
            max_new_hotspots=_optional_int(thresholds.get("max_new_hotspots")),
        ),
        observed=QualityGateObserved(
            new_critical_findings=int(observed.get("new_critical_findings", 0)),
            risk_score=_optional_float(observed.get("risk_score")),
            new_hotspots=int(observed.get("new_hotspots", 0)),
        ),
    )


def _baseline_id_from_json(value: dict[str, Any]) -> UUID | None:
    baseline = value.get("baseline_analysis_id")
    return UUID(str(baseline)) if baseline else None


def _file_insights_from_json(value: dict[str, Any]) -> tuple[FileInsight, ...]:
    return tuple(
        FileInsight(
            path=str(item["path"]),
            hotspot_score=float(item["hotspot_score"]),
            risk=_risk_from_json(item.get("risk")),
            metrics={
                str(key): float(metric) for key, metric in dict(item.get("metrics", {})).items()
            },
        )
        for item in value.get("file_insights", [])
    )


def _quality_policy_from_summary_json(value: dict[str, Any]) -> QualityGatePolicy | None:
    policy = value.get("quality_policy")
    return _quality_policy_from_json(policy) if policy is not None else None


def _risk_to_json(risk: RiskAssessment) -> dict[str, object]:
    return {
        "score": risk.score,
        "category": risk.category,
        "version": risk.version,
        "components": risk.components,
        "weights": risk.weights,
    }


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _risk_from_json(value: Any) -> RiskAssessment | None:
    if value is None:
        return None
    return RiskAssessment(
        score=float(value["score"]),
        category=str(value["category"]),
        version=str(value["version"]),
        components={
            str(key): float(item) for key, item in dict(value.get("components", {})).items()
        },
        weights={str(key): float(item) for key, item in dict(value.get("weights", {})).items()},
    )


def _history_from_record(
    record: AnalysisRecord, project: ProjectRecord | None
) -> AnalysisHistoryRecord:
    summary = record.summary
    if summary is None:
        raise ValueError("completed history record requires a summary")
    risk = summary.risk_assessment
    return AnalysisHistoryRecord(
        analysis_id=record.analysis_id,
        project_id=record.project_id,
        repository_name=project.name if project is not None else record.repository_url,
        repository_url=record.repository_url,
        created_at=record.created_at,
        risk_score=risk.score if risk is not None else None,
        risk_category=risk.category if risk is not None else None,
        finding_count=sum(summary.finding_count_by_severity.values()),
        analyzed_file_count=summary.analyzed_file_count,
        duration_seconds=summary.duration_seconds,
    )


def _history_from_row(row: Any) -> AnalysisHistoryRecord:
    summary = _summary_from_json(row["summary"])
    if summary is None:
        raise ValueError("completed history row requires a summary")
    risk = summary.risk_assessment
    return AnalysisHistoryRecord(
        analysis_id=cast(UUID, row["analysis_id"]),
        project_id=cast(UUID | None, row.get("project_id")),
        repository_name=cast(str | None, row.get("repository_name")) or row["repository_url"],
        repository_url=cast(str, row["repository_url"]),
        created_at=cast(datetime, row["created_at"]),
        risk_score=risk.score if risk is not None else None,
        risk_category=risk.category if risk is not None else None,
        finding_count=sum(summary.finding_count_by_severity.values()),
        analyzed_file_count=summary.analyzed_file_count,
        duration_seconds=summary.duration_seconds,
    )


def _llm_configuration_from_row(value: Any) -> LlmConfiguration:
    return LlmConfiguration(
        workspace_id=str(value["workspace_id"]),
        enabled=bool(value["enabled"]),
        provider=str(value["provider"]),
        model=str(value["model"]),
        encrypted_api_key=value.get("encrypted_api_key"),
        updated_at=value["updated_at"],
    )
