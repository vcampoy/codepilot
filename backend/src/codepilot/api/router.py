"""Top-level API routes."""

from fastapi import APIRouter

from codepilot.api.v1.router import router as v1_router

router = APIRouter()


@router.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Report process health without checking future external dependencies."""
    return {"status": "ok"}


@router.get("/health/live", tags=["health"])
async def liveness() -> dict[str, str]:
    """Kubernetes-style process liveness probe."""
    return {"status": "ok"}


@router.get("/health/ready", tags=["health"])
async def readiness() -> dict[str, str]:
    """Readiness probe for the configured application process."""
    return {"status": "ok"}


router.include_router(v1_router, prefix="/api/v1")
