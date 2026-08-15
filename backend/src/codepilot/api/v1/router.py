"""Version 1 API discovery route."""

from fastapi import APIRouter

from codepilot.api.v1.analyses import router as analyses_router
from codepilot.api.v1.fixes import router as fixes_router
from codepilot.api.v1.github import router as github_router
from codepilot.api.v1.llm import router as llm_router
from codepilot.api.v1.projects import router as projects_router
from codepilot.api.v1.repositories import router as repositories_router

router = APIRouter()


@router.get("/", tags=["discovery"])
async def discover_api() -> dict[str, str]:
    """Identify the current public API surface."""
    return {"name": "CodePilot API", "version": "v1"}


router.include_router(analyses_router)
router.include_router(github_router)
router.include_router(llm_router)
router.include_router(projects_router)
router.include_router(repositories_router)
router.include_router(fixes_router)
