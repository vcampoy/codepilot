# ruff: noqa: E501
"""HTTP endpoints for queued repository analyses."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, Field

from codepilot.analyzers.risk_score import (
    QualityGateObserved,
    QualityGateThresholds,
    RiskAssessment,
)
from codepilot.core.auth import authenticate
from codepilot.core.errors import ApplicationError
from codepilot.domain.analysis import (
    AnalysisFinding,
    AnalysisNotFoundError,
    AnalysisRecord,
    SourceContext,
)
from codepilot.domain.insights import FileInsight, select_hotspots
from codepilot.llm.contracts import EnrichmentResult, EnrichmentTask, LlmError
from codepilot.services.analysis import (
    AnalysisDeletionConflictError,
    AnalysisEnqueueError,
    AnalysisService,
)
from codepilot.services.llm_enrichment import (
    AnalysisNotReadyForEnrichmentError,
    LlmEnrichmentService,
)

router = APIRouter(prefix="/analyses", tags=["analyses"])


class AnalysisRequest(BaseModel):
    """Public analysis request payload."""

    repository_url: str = Field(min_length=1, max_length=2048)


class AnalysisAcceptedResponse(BaseModel):
    """Identifier returned after durable queueing."""

    analysis_id: UUID
    status: str
    project_id: UUID | None = None


class AnalysisStatusResponse(BaseModel):
    """Safe persisted analysis state."""

    analysis_id: UUID
    status: str
    commit_sha: str | None
    failure_message: str | None
    retryable: bool


class AnalysisSummaryResponse(BaseModel):
    """Persisted aggregate metrics, when available."""

    analysis_id: UUID
    status: str
    summary: dict[str, object] | None


class AnalysisHistoryItemResponse(BaseModel):
    analysis_id: UUID
    project_id: UUID | None
    repository_name: str
    repository_url: str
    created_at: str
    risk_score: float | None
    risk_category: str | None
    finding_count: int
    analyzed_file_count: int
    duration_seconds: float


class AnalysisHistoryResponse(BaseModel):
    items: list[AnalysisHistoryItemResponse]
    total: int
    limit: int
    offset: int


class RiskAssessmentResponse(BaseModel):
    score: float
    category: str
    version: str
    components: dict[str, float]
    weights: dict[str, float]


class QualityGateFailureResponse(BaseModel):
    code: str
    detail: str


class QualityGateResponse(BaseModel):
    passed: bool
    configured: bool
    status: str
    failures: list[QualityGateFailureResponse]
    thresholds: dict[str, int | float | None]
    observed: dict[str, int | float | None]


class AnalyzerAvailabilityResponse(BaseModel):
    """Availability of supported external analyzers on this worker image."""

    analyzer: str
    status: str
    tool: str


class AnalysisFindingResponse(BaseModel):
    path: str
    rule_id: str
    analyzer: str
    severity: str
    message: str
    start_line: int
    end_line: int
    category: str
    title: str | None
    evidence: str | None
    remediation: str | None
    source_context: dict[str, object] | None = None


class FileInsightResponse(BaseModel):
    path: str
    hotspot_score: float
    risk: RiskAssessmentResponse | None
    metrics: dict[str, float]


class FileDetailResponse(FileInsightResponse):
    findings: list[AnalysisFindingResponse]


class AnalysisFilesResponse(BaseModel):
    items: list[FileInsightResponse]
    total: int
    limit: int
    offset: int


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=AnalysisAcceptedResponse)
async def request_analysis(payload: AnalysisRequest, request: Request) -> AnalysisAcceptedResponse:
    service = _service(request)
    identity = authenticate(request)
    if not await request.app.state.workspace_quota.consume(identity.workspace_id):
        raise ApplicationError(
            "workspace_quota_exceeded",
            "The workspace analysis quota has been reached.",
            status_code=429,
        )
    try:
        record = await service.request_analysis(payload.repository_url, identity.workspace_id)
    except AnalysisEnqueueError as error:
        raise ApplicationError(
            "analysis_enqueue_failed",
            "Analysis could not be queued.",
            status_code=503,
        ) from error
    return AnalysisAcceptedResponse(
        analysis_id=record.analysis_id,
        status=record.status.value,
        project_id=record.project_id,
    )


@router.get("/analyzers/availability", response_model=list[AnalyzerAvailabilityResponse])
async def analyzer_availability() -> list[AnalyzerAvailabilityResponse]:
    """Report configured worker capabilities; run evidence lives in each summary."""
    availability = [
        AnalyzerAvailabilityResponse(
            analyzer=analyzer,
            status="available",
            tool=tool,
        )
        for analyzer, tool in (
            ("python.ruff", "ruff"),
            ("python.bandit", "bandit"),
            ("python.radon", "radon"),
            ("javascript.eslint", "eslint"),
        )
    ]
    availability.append(
        AnalyzerAvailabilityResponse(
            analyzer="sarif.import", status="not_requested", tool="uploaded-artifact"
        )
    )
    return availability


@router.get("/history", response_model=AnalysisHistoryResponse)
async def analysis_history(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> AnalysisHistoryResponse:
    identity = authenticate(request)
    items, total = await _service(request).list_history(
        identity.workspace_id, limit=limit, offset=offset
    )
    return AnalysisHistoryResponse(
        items=[
            AnalysisHistoryItemResponse(
                analysis_id=item.analysis_id,
                project_id=item.project_id,
                repository_name=item.repository_name,
                repository_url=item.repository_url,
                created_at=item.created_at.isoformat(),
                risk_score=item.risk_score,
                risk_category=item.risk_category,
                finding_count=item.finding_count,
                analyzed_file_count=item.analyzed_file_count,
                duration_seconds=item.duration_seconds,
            )
            for item in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete("/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_analysis(analysis_id: UUID, request: Request) -> None:
    identity = authenticate(request)
    try:
        await _service(request).delete_analysis(analysis_id, identity.workspace_id)
    except AnalysisNotFoundError as error:
        raise ApplicationError(
            "analysis_not_found", "Analysis was not found.", status_code=404
        ) from error
    except AnalysisDeletionConflictError as error:
        raise ApplicationError(
            "analysis_not_ready", "Only completed analyses can be deleted.", status_code=409
        ) from error


@router.post(
    "/{analysis_id}/enrichment/{task}",
    response_model=EnrichmentResult,
)
async def analysis_enrichment(
    analysis_id: UUID, task: EnrichmentTask, request: Request, path: str | None = None
) -> EnrichmentResult:
    record = await _get_record(request, analysis_id)
    service = cast(LlmEnrichmentService, request.app.state.llm_enrichment_service)
    identity = authenticate(request)
    configuration_service = getattr(request.app.state, "llm_configuration_service", None)
    try:
        gateway = (
            await configuration_service.gateway(identity.workspace_id)
            if configuration_service is not None
            else None
        )
        return await service.enrich_analysis(record, task, path, gateway=gateway)
    except AnalysisNotReadyForEnrichmentError as error:
        raise ApplicationError(
            "analysis_not_ready",
            "Deterministic analysis evidence is not available yet.",
            status_code=409,
        ) from error
    except LlmError as error:
        raise ApplicationError(
            "llm_enrichment_unavailable",
            "AI enrichment is unavailable; deterministic analysis remains available.",
            status_code=503,
        ) from error
    except RuntimeError as error:
        raise ApplicationError(
            "llm_enrichment_unavailable",
            "AI enrichment is unavailable; deterministic analysis remains available.",
            status_code=503,
        ) from error


@router.get("/{analysis_id}", response_model=AnalysisStatusResponse)
async def analysis_status(analysis_id: UUID, request: Request) -> AnalysisStatusResponse:
    record = await _get_record(request, analysis_id)
    return AnalysisStatusResponse(
        analysis_id=record.analysis_id,
        status=record.status.value,
        commit_sha=record.commit_sha,
        failure_message=record.failure_message,
        retryable=record.retryable,
    )


@router.get("/{analysis_id}/summary", response_model=AnalysisSummaryResponse)
async def analysis_summary(analysis_id: UUID, request: Request) -> AnalysisSummaryResponse:
    record = await _get_record(request, analysis_id)
    summary = record.summary
    summary_payload: dict[str, object] | None = None
    if summary is not None:
        summary_payload = {
            "analyzed_file_count": summary.analyzed_file_count,
            "source_lines": summary.source_lines,
            "finding_count_by_severity": summary.finding_count_by_severity,
            "duration_seconds": summary.duration_seconds,
            "analyzer_outcomes": [
                {
                    "analyzer": item.analyzer,
                    "tool": item.tool,
                    "version": item.version,
                    "status": item.status,
                    "duration_seconds": item.duration_seconds,
                    "message": item.message,
                    "language": item.language,
                    "generic": item.generic,
                }
                for item in summary.analyzer_outcomes
            ],
        }
        if summary.risk_assessment is not None:
            summary_payload["risk_assessment"] = _risk_response(
                summary.risk_assessment
            ).model_dump()
        if summary.quality_gate is not None:
            summary_payload["quality_gate"] = {
                "passed": summary.quality_gate.passed,
                "configured": summary.quality_gate.configured,
                "status": summary.quality_gate.status,
                "failures": [
                    {"code": failure.code, "detail": failure.detail}
                    for failure in summary.quality_gate.failures
                ],
                "thresholds": _quality_gate_thresholds_response(summary.quality_gate.thresholds),
                "observed": _quality_gate_observed_response(summary.quality_gate.observed),
            }
        if summary.quality_policy is not None:
            summary_payload["quality_policy"] = {
                "version": summary.quality_policy.version,
                "configured": bool(summary.quality_policy.profiles)
                or any(
                    value is not None
                    for value in (
                        summary.quality_policy.thresholds.max_new_critical_findings,
                        summary.quality_policy.thresholds.max_risk_score,
                        summary.quality_policy.thresholds.max_new_hotspots,
                    )
                ),
                "max_new_critical_findings": summary.quality_policy.thresholds.max_new_critical_findings,
                "max_risk_score": summary.quality_policy.thresholds.max_risk_score,
                "max_new_hotspots": summary.quality_policy.thresholds.max_new_hotspots,
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
                    for profile in summary.quality_policy.profiles
                ],
            }
        if summary.baseline_analysis_id is not None:
            summary_payload["baseline_analysis_id"] = str(summary.baseline_analysis_id)
        if summary.file_insights:
            summary_payload["hotspot_count"] = len(select_hotspots(summary.file_insights))
    return AnalysisSummaryResponse(
        analysis_id=record.analysis_id,
        status=record.status.value,
        summary=summary_payload,
    )


@router.get("/{analysis_id}/hotspots", response_model=list[FileInsightResponse])
async def analysis_hotspots(
    analysis_id: UUID,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[FileInsightResponse]:
    record = await _get_record(request, analysis_id)
    if record.summary is None:
        return []
    return [
        _file_insight_response(item)
        for item in select_hotspots(record.summary.file_insights, limit=limit)
    ]


@router.get("/{analysis_id}/files", response_model=AnalysisFilesResponse)
async def analysis_files(
    analysis_id: UUID,
    request: Request,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> AnalysisFilesResponse:
    record = await _get_record(request, analysis_id)
    insights = tuple(
        sorted(
            record.summary.file_insights if record.summary else (),
            key=lambda item: (-item.hotspot_score, item.path),
        )
    )
    return AnalysisFilesResponse(
        items=[_file_insight_response(item) for item in insights[offset : offset + limit]],
        total=len(insights),
        limit=limit,
        offset=offset,
    )


@router.get("/{analysis_id}/files/detail", response_model=FileDetailResponse)
async def analysis_file_detail(
    analysis_id: UUID, request: Request, path: str = Query(min_length=1, max_length=2048)
) -> FileDetailResponse:
    record = await _get_record(request, analysis_id)
    if record.summary is None:
        raise ApplicationError(
            "analysis_not_ready",
            "Deterministic analysis evidence is not available yet.",
            status_code=409,
        )
    normalized = path.replace("\\", "/")
    insight = next((item for item in record.summary.file_insights if item.path == normalized), None)
    if insight is None:
        raise ApplicationError("file_not_found", "File insight was not found.", status_code=404)
    findings = await _service(request).get_findings(analysis_id, authenticate(request).workspace_id)
    response = _file_insight_response(insight)
    return FileDetailResponse(
        **response.model_dump(),
        findings=[_finding_response(finding) for finding in findings if finding.path == normalized],
    )


@router.get("/{analysis_id}/findings", response_model=list[AnalysisFindingResponse])
async def analysis_findings(analysis_id: UUID, request: Request) -> list[AnalysisFindingResponse]:
    identity = authenticate(request)
    try:
        findings = await _service(request).get_findings(analysis_id, identity.workspace_id)
    except AnalysisNotFoundError as error:
        raise ApplicationError(
            "analysis_not_found", "Analysis was not found.", status_code=404
        ) from error
    return [
        AnalysisFindingResponse(
            path=finding.path,
            rule_id=finding.rule_id,
            analyzer=finding.analyzer,
            severity=finding.severity,
            message=finding.message,
            start_line=finding.start_line,
            end_line=finding.end_line,
            category=finding.category,
            title=finding.title,
            evidence=finding.evidence,
            remediation=finding.remediation,
            source_context=_source_context_response(finding.source_context),
        )
        for finding in findings
    ]


def _service(request: Request) -> AnalysisService:
    return cast(AnalysisService, request.app.state.analysis_service)


async def _get_record(request: Request, analysis_id: UUID) -> AnalysisRecord:
    identity = authenticate(request)
    try:
        return await _service(request).get_analysis(analysis_id, identity.workspace_id)
    except AnalysisNotFoundError as error:
        raise ApplicationError(
            "analysis_not_found", "Analysis was not found.", status_code=404
        ) from error


def _risk_response(risk: object) -> RiskAssessmentResponse:
    assessment = cast(RiskAssessment, risk)
    return RiskAssessmentResponse(
        score=assessment.score,
        category=assessment.category,
        version=assessment.version,
        components=assessment.components,
        weights=assessment.weights,
    )


def _file_insight_response(insight: FileInsight) -> FileInsightResponse:
    return FileInsightResponse(
        path=insight.path,
        hotspot_score=insight.hotspot_score,
        risk=(_risk_response(insight.risk) if insight.risk else None),
        metrics=insight.metrics,
    )


def _quality_gate_thresholds_response(
    thresholds: QualityGateThresholds,
) -> dict[str, int | float | None]:
    return {
        "max_new_critical_findings": thresholds.max_new_critical_findings,
        "max_risk_score": thresholds.max_risk_score,
        "max_new_hotspots": thresholds.max_new_hotspots,
    }


def _quality_gate_observed_response(
    observed: QualityGateObserved,
) -> dict[str, int | float | None]:
    return {
        "new_critical_findings": observed.new_critical_findings,
        "risk_score": observed.risk_score,
        "new_hotspots": observed.new_hotspots,
    }


def _finding_response(finding: object) -> AnalysisFindingResponse:
    item = cast(AnalysisFinding, finding)
    return AnalysisFindingResponse(
        path=item.path,
        rule_id=item.rule_id,
        analyzer=item.analyzer,
        severity=item.severity,
        message=item.message,
        start_line=item.start_line,
        end_line=item.end_line,
        category=item.category,
        title=item.title,
        evidence=item.evidence,
        remediation=item.remediation,
        source_context=_source_context_response(item.source_context),
    )


def _source_context_response(context: object) -> dict[str, object] | None:
    if context is None:
        return None
    item = cast(SourceContext, context)
    return {
        "start_line": item.start_line,
        "end_line": item.end_line,
        "lines": [
            {"number": line.number, "text": line.text, "highlighted": line.highlighted}
            for line in item.lines
        ],
    }
