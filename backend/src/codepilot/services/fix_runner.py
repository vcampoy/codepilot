"""Application runner for persisted Fix Findings jobs.

The runner owns lifecycle transitions; external repair systems are injected as
ports so Celery remains a delivery mechanism rather than business logic.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from codepilot.domain.analysis import AnalysisFinding, AnalysisStatus, fingerprint_finding
from codepilot.domain.fixes import FixJobStatus, FixTargetType
from codepilot.repositories.fixes import FixRepository
from codepilot.services.fixes import AnalysisFixSource
from codepilot.services.repair import RepairExecutionError, RepairExecutor, RepairRequest


class FixJobRunner:
    def __init__(
        self,
        analysis_repository: AnalysisFixSource,
        repository: FixRepository,
        executor: RepairExecutor,
    ) -> None:
        self._analysis_repository = analysis_repository
        self._repository = repository
        self._executor = executor

    async def run(self, job_id: UUID) -> None:
        job = await self._repository.get_job(job_id)
        if job is None:
            return
        claimed = await self._repository.claim_job(job_id, job.workspace_id)
        if claimed is None:
            return
        try:
            analysis = await self._analysis_repository.get(
                claimed.analysis_id, claimed.workspace_id
            )
            if analysis is None or analysis.status is not AnalysisStatus.COMPLETED:
                raise RepairExecutionError("Analysis is not available for repair.")
            if not analysis.commit_sha:
                raise RepairExecutionError("Analysis commit is not available for repair.")
            configuration = await self._repository.get_configuration(claimed.workspace_id)
            evidence = await self._evidence(
                claimed.target_type, claimed.target_ids, claimed.analysis_id
            )
            rules = (
                configuration.hotspot_rules or ""
                if claimed.target_type is FixTargetType.HOTSPOT
                else configuration.finding_rules or configuration.rules
            )
            request = RepairRequest(
                claimed.target_type,
                claimed.target_ids,
                evidence,
                rules,
                claimed.workspace_id,
            )
            url = await self._executor.execute(
                request,
                repository_url=analysis.repository_url,
                commit_sha=analysis.commit_sha,
                branch_name=claimed.branch_name or self._fallback_branch(claimed.job_id),
                base_branch=analysis.branch_name,
            )
        except Exception as error:  # noqa: BLE001 - state must always terminalize safely
            await self._repository.update_job(
                claimed.job_id,
                status=FixJobStatus.FAILED,
                workspace_id=claimed.workspace_id,
                error_message=_safe_error(error),
            )
            return
        await self._repository.update_job(
            claimed.job_id,
            status=FixJobStatus.SUCCEEDED,
            workspace_id=claimed.workspace_id,
            pull_request_url=url,
        )

    async def _evidence(
        self, target_type: FixTargetType, target_ids: Sequence[str], analysis_id: UUID
    ) -> tuple[dict[str, object], ...]:
        if target_type is FixTargetType.HOTSPOT:
            insights = await self._analysis_repository.get_file_insights(analysis_id)
            by_path = {item.path: item for item in insights}
            evidence = tuple(
                {"path": path, "hotspot_score": by_path[path].hotspot_score}
                for path in target_ids
                if path in by_path
            )
            if len(evidence) != len(target_ids):
                raise RepairExecutionError("One or more selected hotspots are unavailable.")
            return evidence
        findings = await self._analysis_repository.get_findings(analysis_id)
        by_id = {fingerprint_finding(item): item for item in findings}
        evidence = tuple(
            _finding_evidence(by_id[item], item) for item in target_ids if item in by_id
        )
        if len(evidence) != len(target_ids):
            raise RepairExecutionError("One or more selected findings are unavailable.")
        return evidence

    @staticmethod
    def _fallback_branch(job_id: UUID) -> str:
        return f"fix-findings-{job_id.hex[:12]}"


def _finding_evidence(finding: AnalysisFinding, finding_id: str) -> dict[str, object]:
    return {
        "finding_id": finding_id,
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
        "source_context": finding.source_context,
    }


def _safe_error(error: Exception) -> str:
    message = str(error).strip()
    if not message or len(message) > 512:
        return "Fix execution failed."
    return message
