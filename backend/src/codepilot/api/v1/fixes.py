"""Fix Findings settings and asynchronous job endpoints."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from codepilot.core.auth import authenticate
from codepilot.core.errors import ApplicationError
from codepilot.domain.fixes import FixConfiguration, FixJob, FixTargetType
from codepilot.services.fixes import FixService, FixValidationError

router = APIRouter(tags=["fixes"])


class FixConfigurationPayload(BaseModel):
    rules: str = Field(default="", max_length=32_000)
    finding_rules: str | None = Field(default=None, max_length=32_000)
    hotspot_rules: str = Field(default="", max_length=32_000)
    max_findings_per_fix: int | None = Field(default=None, ge=1, le=10)


class FixConfigurationResponse(BaseModel):
    rules: str
    finding_rules: str = ""
    hotspot_rules: str = ""
    updated_at: str
    max_findings_per_fix: int = 10


class FixJobPayload(BaseModel):
    finding_ids: list[str] | None = Field(default=None, min_length=1)
    target_ids: list[str] | None = Field(default=None, min_length=1)
    target_type: FixTargetType = FixTargetType.FINDING

    @property
    def normalized_target_ids(self) -> list[str]:
        return self.target_ids or self.finding_ids or []


class FixJobResponse(BaseModel):
    job_id: UUID
    analysis_id: UUID
    status: str
    finding_ids: list[str]
    target_type: str
    target_ids: list[str]
    branch_name: str | None
    pull_request_url: str | None
    error_message: str | None
    created_at: str
    updated_at: str


@router.get("/settings/fixes", response_model=FixConfigurationResponse)
async def get_fix_configuration(request: Request) -> FixConfigurationResponse:
    identity = authenticate(request)
    return _configuration(await _service(request).get_rules(identity.workspace_id))


@router.put("/settings/fixes", response_model=FixConfigurationResponse)
async def save_fix_configuration(
    payload: FixConfigurationPayload, request: Request
) -> FixConfigurationResponse:
    identity = authenticate(request)
    try:
        return _configuration(
            await _service(request).save_configuration(
                identity.workspace_id,
                finding_rules=(
                    payload.finding_rules if payload.finding_rules is not None else payload.rules
                ),
                hotspot_rules=payload.hotspot_rules,
                max_findings_per_fix=payload.max_findings_per_fix,
            )
        )
    except FixValidationError as error:
        raise ApplicationError("invalid_fix_configuration", str(error), status_code=400) from error


@router.post(
    "/analyses/{analysis_id}/fix-jobs",
    response_model=FixJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_fix_job(
    analysis_id: UUID, payload: FixJobPayload, request: Request
) -> FixJobResponse:
    identity = authenticate(request)
    try:
        job = await _service(request).create_job(
            analysis_id,
            payload.normalized_target_ids,
            identity.workspace_id,
            target_type=payload.target_type,
        )
    except FixValidationError as error:
        raise ApplicationError("invalid_fix_job", str(error), status_code=400) from error
    except RuntimeError as error:
        raise ApplicationError("fix_job_unavailable", str(error), status_code=503) from error
    return _job(job)


@router.get("/fix-jobs/{job_id}", response_model=FixJobResponse)
async def get_fix_job(job_id: UUID, request: Request) -> FixJobResponse:
    identity = authenticate(request)
    try:
        return _job(await _service(request).get_job(job_id, identity.workspace_id))
    except FixValidationError as error:
        raise ApplicationError("fix_job_not_found", str(error), status_code=404) from error


def _service(request: Request) -> FixService:
    return cast(FixService, request.app.state.fix_service)


def _configuration(value: FixConfiguration) -> FixConfigurationResponse:
    return FixConfigurationResponse(
        rules=value.rules,
        finding_rules=value.finding_rules or value.rules,
        hotspot_rules=value.hotspot_rules or "",
        updated_at=value.updated_at.isoformat(),
        max_findings_per_fix=value.max_findings_per_fix,
    )


def _job(value: FixJob) -> FixJobResponse:
    return FixJobResponse(
        job_id=value.job_id,
        analysis_id=value.analysis_id,
        status=value.status.value,
        finding_ids=list(value.finding_ids),
        target_type=value.target_type.value,
        target_ids=list(value.target_ids),
        branch_name=value.branch_name,
        pull_request_url=value.pull_request_url,
        error_message=value.error_message,
        created_at=value.created_at.isoformat(),
        updated_at=value.updated_at.isoformat(),
    )
