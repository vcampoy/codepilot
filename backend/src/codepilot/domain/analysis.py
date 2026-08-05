"""Domain objects for asynchronous repository analysis."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Final
from uuid import UUID


class AnalysisStatus(StrEnum):
    """Persisted lifecycle states for one analysis request."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class InvalidAnalysisTransitionError(Exception):
    """The analysis lifecycle transition is not allowed."""


class AnalysisNotFoundError(Exception):
    """The requested analysis does not exist in the source of truth."""


@dataclass(frozen=True, slots=True)
class AnalysisFinding:
    """A finding produced by an analyzer without repository content."""

    path: str
    rule_id: str
    severity: str
    message: str
    start_line: int
    end_line: int


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Analyzer output that can be persisted independently of Celery."""

    analyzed_file_count: int
    source_lines: int
    findings: tuple[AnalysisFinding, ...]


@dataclass(frozen=True, slots=True)
class AnalysisSummary:
    """Persisted aggregate metrics for a completed analysis."""

    analyzed_file_count: int
    source_lines: int
    finding_count_by_severity: dict[str, int]
    duration_seconds: float


@dataclass(slots=True)
class AnalysisRecord:
    """Persisted analysis state and safe failure information."""

    analysis_id: UUID
    repository_url: str
    workspace_id: str = "default"
    status: AnalysisStatus = AnalysisStatus.QUEUED
    commit_sha: str | None = None
    summary: AnalysisSummary | None = None
    failure_message: str | None = None
    retryable: bool = False
    running_at: datetime | None = None
    lease_expires_at: datetime | None = None
    lease_token: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


_FINGERPRINT_FIELDS: Final[tuple[str, ...]] = (
    "path",
    "rule_id",
    "severity",
    "message",
    "start_line",
    "end_line",
)


def fingerprint_finding(finding: AnalysisFinding) -> str:
    """Return a stable digest for the logical identity of a finding."""
    values = {field: getattr(finding, field) for field in _FINGERPRINT_FIELDS}
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()
