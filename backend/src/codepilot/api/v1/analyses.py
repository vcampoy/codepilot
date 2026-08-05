"""HTTP endpoints for queued repository analyses."""

from __future__ import annotations

import shutil
from typing import cast
from uuid import UUID

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from codepilot.core.errors import ApplicationError
from codepilot.domain.analysis import AnalysisNotFoundError, AnalysisRecord
from codepilot.services.analysis import AnalysisEnqueueError, AnalysisService

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


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=AnalysisAcceptedResponse)
async def request_analysis(
    payload: AnalysisRequest, request: Request
) -> AnalysisAcceptedResponse:
    service = _service(request)
    try:
        record = await service.request_analysis(payload.repository_url)
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
    """Report whether optional external analyzer executables are installed."""
    return [
        AnalyzerAvailabilityResponse(
            analyzer=analyzer,
            status="available" if shutil.which(tool) else "skipped",
            tool=tool,
        )
        for analyzer, tool in (
            ("python.ruff", "ruff"),
            ("python.bandit", "bandit"),
            ("python.radon", "radon"),
            ("javascript.eslint", "eslint"),
            ("sarif.import", "uploaded-artifact"),
        )
    ]


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
async def analysis_summary(
    analysis_id: UUID, request: Request
) -> AnalysisSummaryResponse:
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
            }
            if summary is not None
            else None
        ),
    )


def _service(request: Request) -> AnalysisService:
    return cast(AnalysisService, request.app.state.analysis_service)


async def _get_record(request: Request, analysis_id: UUID) -> AnalysisRecord:
    try:
        return await _service(request).get_analysis(analysis_id)
    except AnalysisNotFoundError as error:
        raise ApplicationError(
            "analysis_not_found", "Analysis was not found.", status_code=404
        ) from error
