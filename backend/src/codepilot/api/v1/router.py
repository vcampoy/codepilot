"""Version 1 API discovery route."""

from fastapi import APIRouter

from codepilot.api.v1.analyses import router as analyses_router

router = APIRouter()


@router.get("/", tags=["discovery"])
async def discover_api() -> dict[str, str]:
    """Identify the current public API surface."""
    return {"name": "CodePilot API", "version": "v1"}


router.include_router(analyses_router)
