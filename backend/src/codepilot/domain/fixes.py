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


class FixTargetType(StrEnum):
    FINDING = "finding"
    HOTSPOT = "hotspot"


@dataclass(frozen=True, slots=True)
class FixConfiguration:
    workspace_id: str
    rules: str = ""
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finding_rules: str | None = None
    hotspot_rules: str | None = None
    max_findings_per_fix: int = 10

    def __post_init__(self) -> None:
        if not 1 <= self.max_findings_per_fix <= 10:
            raise ValueError("max_findings_per_fix must be between 1 and 10")
        # Keep the legacy ``rules`` field as the findings rules for clients that
        # have not migrated yet.
        if self.finding_rules is None:
            object.__setattr__(self, "finding_rules", self.rules)
        if self.hotspot_rules is None:
            object.__setattr__(self, "hotspot_rules", "")


@dataclass(slots=True)
class FixJob:
    job_id: UUID = field(default_factory=uuid4)
    analysis_id: UUID = field(default_factory=uuid4)
    workspace_id: str = "default"
    finding_ids: tuple[str, ...] = ()
    target_type: FixTargetType = FixTargetType.FINDING
    target_ids: tuple[str, ...] = ()
    status: FixJobStatus = FixJobStatus.QUEUED
    branch_name: str | None = None
    pull_request_url: str | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.target_ids:
            self.target_ids = tuple(self.finding_ids)
        if not self.finding_ids and self.target_type is FixTargetType.FINDING:
            self.finding_ids = tuple(self.target_ids)
