from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from codepilot.core.auth import authenticate
from codepilot.domain.analysis import AnalysisRecord, ProjectRecord
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
