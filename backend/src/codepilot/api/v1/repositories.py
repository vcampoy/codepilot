"""Repository discovery endpoints."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from codepilot.core.auth import authenticate
from codepilot.core.errors import ApplicationError
from codepilot.services.analysis import AnalysisService
from codepilot.services.repository_ingestion import RepositoryIngestionError

router = APIRouter(prefix="/repositories", tags=["repositories"])


class RepositoryBranchesRequest(BaseModel):
    repository_url: str = Field(min_length=1, max_length=2048)


class RepositoryBranchesResponse(BaseModel):
    branches: list[str]
    default_branch: str


@router.post("/branches", response_model=RepositoryBranchesResponse)
async def list_repository_branches(
    payload: RepositoryBranchesRequest, request: Request
) -> RepositoryBranchesResponse:
    authenticate(request)
    try:
        result = await _service(request).list_repository_branches(payload.repository_url)
    except RepositoryIngestionError as error:
        raise ApplicationError(error.code, str(error), status_code=400) from error
    return RepositoryBranchesResponse(
        branches=list(result.branches), default_branch=result.default_branch
    )


def _service(request: Request) -> AnalysisService:
    return cast(AnalysisService, request.app.state.analysis_service)
