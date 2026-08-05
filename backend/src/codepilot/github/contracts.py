"""Typed contracts for GitHub App integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field


class GitHubWebhookEvent(BaseModel):
    """Normalized event data safe for application dispatch."""

    delivery_id: str = Field(min_length=1, max_length=256)
    event_name: Literal["push", "pull_request"]
    action: str | None = Field(default=None, max_length=64)
    repository: str = Field(min_length=1, max_length=256)
    installation_id: int | None = Field(default=None, ge=1)
    pull_request_number: int | None = Field(default=None, ge=1)
    before_sha: str | None = Field(default=None, max_length=128)
    after_sha: str | None = Field(default=None, max_length=128)


class WebhookProcessingResult(BaseModel):
    """Acknowledgement that distinguishes replay from first delivery."""

    accepted: bool
    duplicate: bool
    event: GitHubWebhookEvent | None = None


class FindingSnapshot(BaseModel):
    """Comparable deterministic finding identity for baseline deltas."""

    finding_id: str = Field(min_length=1, max_length=256)
    path: str = Field(min_length=1, max_length=512)
    severity: str = Field(min_length=1, max_length=32)


class QualityGateFailure(BaseModel):
    """Serializable quality-gate failure for GitHub output."""

    code: str
    detail: str


class QualityGateSummary(BaseModel):
    """Serializable quality-gate result for the PR contract."""

    passed: bool
    failures: tuple[QualityGateFailure, ...]


class PullRequestComparison(BaseModel):
    """Focused PR delta and quality-gate outcome."""

    new_findings: tuple[FindingSnapshot, ...]
    resolved_findings: tuple[FindingSnapshot, ...]
    risk_delta: float
    new_hotspots: tuple[str, ...]
    quality_gate: QualityGateSummary


@dataclass(frozen=True, slots=True)
class GitHubResponse:
    """Transport-neutral GitHub response used by the dedicated adapter."""

    status_code: int
    headers: dict[str, str]
    payload: Any
    text: str = ""
