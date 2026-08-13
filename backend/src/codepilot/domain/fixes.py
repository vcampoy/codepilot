"""Domain contracts for asynchronous finding repair jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


class FixJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class FixConfiguration:
    workspace_id: str
    rules: str = ""
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class FixJob:
    job_id: UUID = field(default_factory=uuid4)
    analysis_id: UUID = field(default_factory=uuid4)
    workspace_id: str = "default"
    finding_ids: tuple[str, ...] = ()
    status: FixJobStatus = FixJobStatus.QUEUED
    branch_name: str | None = None
    pull_request_url: str | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
