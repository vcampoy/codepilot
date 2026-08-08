"""HTTP endpoints for queued repository analyses."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from codepilot.core.auth import authenticate
from codepilot.core.errors import ApplicationError
from codepilot.domain.analysis import AnalysisNotFoundError, AnalysisRecord
from codepilot.llm.contracts import EnrichmentResult, EnrichmentTask, LlmError
from codepilot.services.analysis import AnalysisEnqueueError, AnalysisService
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


@router.post(
    "/{analysis_id}/enrichment/{task}",
    response_model=EnrichmentResult,
)
async def analysis_enrichment(
    analysis_id: UUID, task: EnrichmentTask, request: Request, path: str | None = None
) -> EnrichmentResult:
    record = await _get_record(request, analysis_id)
    service = cast(LlmEnrichmentService, request.app.state.llm_enrichment_service)
    try:
        return await service.enrich_analysis(record, task, path)
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
    return AnalysisSummaryResponse(
        analysis_id=record.analysis_id,
        status=record.status.value,
        summary=(
            {
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
            if summary is not None
            else None
        ),
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
