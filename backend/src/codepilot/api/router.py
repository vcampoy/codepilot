"""Top-level API routes."""

from fastapi import APIRouter

from codepilot.api.v1.router import router as v1_router

router = APIRouter()


@router.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Report process health without checking future external dependencies."""
    return {"status": "ok"}


router.include_router(v1_router, prefix="/api/v1")
