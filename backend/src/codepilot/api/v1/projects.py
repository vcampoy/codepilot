# ruff: noqa: E501
from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from codepilot.analyzers.risk_score import QualityGateConfig
from codepilot.core.auth import authenticate
from codepilot.domain.analysis import AnalysisRecord, ProjectRecord
from codepilot.domain.quality import (
    QualityGatePolicy,
    QualityProfile,
    QualityRule,
    parse_sonar_profile_xml,
)
from codepilot.services.analysis import AnalysisService

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectResponse(BaseModel):
    project_id: UUID
    name: str
    repository_url: str
    created_at: str
    updated_at: str


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]
    total: int
    limit: int
    offset: int


class AnalysisRunResponse(BaseModel):
    analysis_id: UUID
    project_id: UUID | None
    status: str
    repository_url: str
    created_at: str
    failure_message: str | None


class AnalysisRunListResponse(BaseModel):
    items: list[AnalysisRunResponse]
    total: int
    limit: int
    offset: int


class QualityRulePayload(BaseModel):
    language: str
    analyzer: str
    rule_id: str
    enabled: bool = True


class QualityProfilePayload(BaseModel):
    language: str
    rules: list[QualityRulePayload] = []


class QualityPolicyPayload(BaseModel):
    version: int = 1
    max_new_critical_findings: int | None = Field(default=None, ge=0)
    max_risk_score: float | None = Field(default=None, ge=0, le=1)
    max_new_hotspots: int | None = Field(default=None, ge=0)
    profiles: list[QualityProfilePayload] = Field(default_factory=list)


class QualityPolicyResponse(QualityPolicyPayload):
    configured: bool


class QualityProfileImportResponse(BaseModel):
    language: str
    profile_name: str | None
    mapped: int
    unsupported: list[str]
    invalid: list[str]


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    request: Request, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)
) -> ProjectListResponse:
    identity = authenticate(request)
    items, total = await _service(request).list_projects(
        identity.workspace_id, limit=limit, offset=offset
    )
    return ProjectListResponse(
        items=[_project(item) for item in items], total=total, limit=limit, offset=offset
    )


@router.get("/{project_id}/analyses", response_model=AnalysisRunListResponse)
async def list_project_analyses(
    project_id: UUID,
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> AnalysisRunListResponse:
    identity = authenticate(request)
    items, total = await _service(request).list_project_analyses(
        project_id, identity.workspace_id, limit=limit, offset=offset
    )
    if not items and offset == 0 and total == 0:
        # Keep tenant boundaries opaque: an unknown project has the same shape as an empty one.
        return AnalysisRunListResponse(items=[], total=0, limit=limit, offset=offset)
    return AnalysisRunListResponse(
        items=[_run(item) for item in items], total=total, limit=limit, offset=offset
    )


@router.get("/{project_id}/quality-policy", response_model=QualityPolicyResponse)
async def get_quality_policy(project_id: UUID, request: Request) -> QualityPolicyResponse:
    identity = authenticate(request)
    policy = await _service(request).get_quality_policy(project_id, identity.workspace_id)
    if policy is None:
        return QualityPolicyResponse(configured=False, profiles=[])
    return _policy_response(policy)


@router.put("/{project_id}/quality-policy", response_model=QualityPolicyResponse)
async def put_quality_policy(
    project_id: UUID, payload: QualityPolicyPayload, request: Request
) -> QualityPolicyResponse:
    identity = authenticate(request)
    current = await _service(request).get_quality_policy(project_id, identity.workspace_id)
    policy = QualityGatePolicy(
        version=(current.version + 1) if current else max(1, payload.version),
        thresholds=QualityGateConfig(
            max_new_critical_findings=payload.max_new_critical_findings,
            max_risk_score=payload.max_risk_score,
            max_new_hotspots=payload.max_new_hotspots,
        ),
        profiles=tuple(
            QualityProfile(
                profile.language,
                tuple(
                    QualityRule(rule.language, rule.analyzer, rule.rule_id, rule.enabled)
                    for rule in profile.rules
                ),
            )
            for profile in payload.profiles
        ),
    )
    try:
        saved = await _service(request).save_quality_policy(
            project_id, identity.workspace_id, policy
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Project not found") from error
    return _policy_response(saved)


@router.post("/{project_id}/quality-profiles/import", response_model=QualityProfileImportResponse)
async def import_quality_profile(
    project_id: UUID, request: Request
) -> QualityProfileImportResponse:
    identity = authenticate(request)
    try:
        content_length = request.headers.get("content-length")
        if content_length is not None and int(content_length) > 1_048_576:
            raise ValueError("quality profile XML exceeds size limit")
        payload = await request.body()
        report = parse_sonar_profile_xml(payload)
        existing = await _service(request).get_quality_policy(project_id, identity.workspace_id)
        policy = existing or QualityGatePolicy()
        profiles = tuple(
            profile for profile in policy.profiles if profile.language != report.language
        ) + (report.profile,)
        await _service(request).save_quality_policy(
            project_id,
            identity.workspace_id,
            QualityGatePolicy(policy.version + 1, policy.thresholds, profiles),
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Project not found") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return QualityProfileImportResponse(
        language=report.language,
        profile_name=report.profile_name,
        mapped=report.mapped,
        unsupported=list(report.unsupported),
        invalid=list(report.invalid),
    )


def _service(request: Request) -> AnalysisService:
    return cast(AnalysisService, request.app.state.analysis_service)


def _project(item: ProjectRecord) -> ProjectResponse:
    project = item
    return ProjectResponse(
        project_id=project.project_id,
        name=project.name,
        repository_url=project.repository_url,
        created_at=project.created_at.isoformat(),
        updated_at=project.updated_at.isoformat(),
    )


def _run(item: AnalysisRecord) -> AnalysisRunResponse:
    run = item
    return AnalysisRunResponse(
        analysis_id=run.analysis_id,
        project_id=run.project_id,
        status=run.status.value,
        repository_url=run.repository_url,
        created_at=run.created_at.isoformat(),
        failure_message=run.failure_message,
    )


def _policy_response(policy: QualityGatePolicy) -> QualityPolicyResponse:
    return QualityPolicyResponse(
        configured=any(
            value is not None
            for value in (
                policy.thresholds.max_new_critical_findings,
                policy.thresholds.max_risk_score,
                policy.thresholds.max_new_hotspots,
            )
        )
        or bool(policy.profiles),
        version=policy.version,
        max_new_critical_findings=policy.thresholds.max_new_critical_findings,
        max_risk_score=policy.thresholds.max_risk_score,
        max_new_hotspots=policy.thresholds.max_new_hotspots,
        profiles=[
            QualityProfilePayload(
                language=profile.language,
                rules=[
                    QualityRulePayload(
                        language=rule.language,
                        analyzer=rule.analyzer,
                        rule_id=rule.rule_id,
                        enabled=rule.enabled,
                    )
                    for rule in profile.rules
                ],
            )
            for profile in policy.profiles
        ],
    )
