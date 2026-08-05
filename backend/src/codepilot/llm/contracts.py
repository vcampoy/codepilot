"""Typed contracts for optional evidence-bound LLM enrichment."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EnrichmentTask(StrEnum):
    """Supported explanation tasks."""

    FILE_RISK = "file-risk"
    REFACTORING_PLAN = "refactoring-plan"
    DETERMINISTIC_SUMMARY = "deterministic-summary"


class EvidenceFinding(BaseModel):
    """A bounded finding stored by deterministic analysis."""

    finding_id: str = Field(min_length=1, max_length=128)
    path: str = Field(min_length=1, max_length=512)
    rule_id: str = Field(min_length=1, max_length=128)
    severity: str = Field(min_length=1, max_length=32)
    message: str = Field(default="", max_length=2048)


class DeterministicEvidence(BaseModel):
    """The only evidence that may cross the LLM boundary."""

    model_config = ConfigDict(frozen=True)

    analysis_id: UUID
    commit_sha: str | None = Field(default=None, max_length=128)
    findings: tuple[EvidenceFinding, ...] = Field(default=(), max_length=500)
    score_components: dict[str, float] = Field(default_factory=dict, max_length=64)
    hotspot_paths: tuple[str, ...] = Field(default=(), max_length=100)
    summary: dict[str, int | float | str] = Field(default_factory=dict, max_length=64)

    def citation_ids(self) -> frozenset[str]:
        """Return stable evidence identifiers accepted in AI output."""
        finding_ids = {finding.finding_id for finding in self.findings}
        score_ids = {f"score:{name}" for name in self.score_components}
        hotspot_ids = {f"hotspot:{path}" for path in self.hotspot_paths}
        return frozenset((*finding_ids, *score_ids, *hotspot_ids))


class LlmUsage(BaseModel):
    """Provider usage and cost, when the provider reports it."""

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)


class ProviderCompletion(BaseModel):
    """Normalized provider response used by the adapter boundary."""

    content: str = Field(min_length=1, max_length=100_000)
    model: str = Field(min_length=1, max_length=256)
    provider: str = Field(min_length=1, max_length=256)
    usage: LlmUsage = Field(default_factory=LlmUsage)


class ExplanationOutput(BaseModel):
    """Structured output for a file-risk explanation."""

    summary: str = Field(min_length=1, max_length=2_000)
    why_it_matters: str = Field(min_length=1, max_length=2_000)
    citations: list[str] = Field(min_length=1, max_length=20)


class RefactoringPlanItem(BaseModel):
    """One evidence-cited refactoring action."""

    priority: int = Field(ge=1, le=5)
    action: str = Field(min_length=1, max_length=1_000)
    rationale: str = Field(min_length=1, max_length=2_000)
    citations: list[str] = Field(min_length=1, max_length=20)


class RefactoringPlanOutput(BaseModel):
    """Structured output for repository prioritization."""

    items: list[RefactoringPlanItem] = Field(min_length=1, max_length=20)


class DeterministicSummaryOutput(BaseModel):
    """Structured output for deterministic finding summaries."""

    summary: str = Field(min_length=1, max_length=3_000)
    key_findings: list[str] = Field(min_length=1, max_length=20)
    citations: list[str] = Field(min_length=1, max_length=20)


class LlmRequest(BaseModel):
    """Provider request with a reproducible cache identity."""

    task: EnrichmentTask
    analysis_id: UUID
    model: str
    prompt_version: str
    system_prompt: str
    user_prompt: str
    max_tokens: int = Field(gt=0, le=8_192)
    cache_key: str


class EnrichmentResult(BaseModel):
    """Public result; AI output is explicitly labeled and traceable."""

    task: EnrichmentTask
    analysis_id: UUID
    enabled: bool
    ai_generated: Literal[True, False]
    text: str | None = None
    structured: dict[str, Any] | None = None
    citations: list[str] = Field(default_factory=list)
    model: str | None = None
    provider: str | None = None
    usage: LlmUsage = Field(default_factory=LlmUsage)
    latency_ms: float = Field(default=0, ge=0)
    cache_hit: bool = False


class LlmError(Exception):
    """Base class for safe, classifiable LLM failures."""


class LlmDisabledError(LlmError):
    """AI enrichment is intentionally disabled."""


class LlmInvalidResponseError(LlmError):
    """The provider returned invalid or untraceable structured output."""


class LlmProviderError(LlmError):
    """The configured provider could not return a completion."""


class NoOpLlmGateway:
    """Safe default that keeps deterministic analysis fully functional."""

    async def enrich(
        self, task: EnrichmentTask, evidence: DeterministicEvidence
    ) -> EnrichmentResult:
        return EnrichmentResult(
            task=task,
            analysis_id=evidence.analysis_id,
            enabled=False,
            ai_generated=False,
        )
