"""Application service that converts persisted analysis evidence into AI output."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from codepilot.domain.analysis import (
    AnalysisFinding,
    AnalysisRecord,
    fingerprint_finding,
)
from codepilot.llm.contracts import (
    DeterministicEvidence,
    EnrichmentResult,
    EnrichmentTask,
    EvidenceFinding,
)


class AnalysisEvidenceRepository(Protocol):
    """Read-only deterministic evidence boundary."""

    async def get_findings(self, analysis_id: UUID) -> tuple[AnalysisFinding, ...]: ...


class LlmGateway(Protocol):
    """Application-owned boundary for optional AI providers."""

    async def enrich(
        self, task: EnrichmentTask, evidence: DeterministicEvidence
    ) -> EnrichmentResult: ...


class LlmEnrichmentService:
    """Build evidence from persisted deterministic analysis data only."""

    def __init__(self, gateway: LlmGateway, repository: AnalysisEvidenceRepository) -> None:
        self._gateway = gateway
        self._repository = repository

    async def enrich_analysis(
        self,
        record: AnalysisRecord,
        task: EnrichmentTask,
        file_path: str | None = None,
        gateway: LlmGateway | None = None,
    ) -> EnrichmentResult:
        if record.summary is None:
            raise AnalysisNotReadyForEnrichmentError
        summary = record.summary
        total_findings = sum(summary.finding_count_by_severity.values())
        stored_findings = await self._repository.get_findings(record.analysis_id)
        if file_path is not None:
            stored_findings = tuple(
                finding for finding in stored_findings if finding.path == file_path
            )
        findings = tuple(
            EvidenceFinding(
                finding_id=fingerprint_finding(finding),
                path=finding.path,
                rule_id=finding.rule_id,
                severity=finding.severity,
                message=finding.message,
            )
            for finding in stored_findings
        )
        evidence = DeterministicEvidence(
            analysis_id=record.analysis_id,
            commit_sha=record.commit_sha,
            findings=findings,
            score_components={
                "analyzed_file_count": float(summary.analyzed_file_count),
                "source_lines": float(summary.source_lines),
                "finding_count": float(total_findings),
                "duration_seconds": summary.duration_seconds,
            },
            summary={
                "analyzed_file_count": summary.analyzed_file_count,
                "source_lines": summary.source_lines,
                "duration_seconds": summary.duration_seconds,
                "finding_count": total_findings,
            },
        )
        return await (gateway or self._gateway).enrich(task, evidence)


class AnalysisNotReadyForEnrichmentError(Exception):
    """The analysis has not persisted deterministic summary evidence yet."""
