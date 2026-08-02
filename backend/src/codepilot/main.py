"""FastAPI application bootstrap."""

from fastapi import FastAPI

from codepilot.api.router import router


def create_app() -> FastAPI:
    """Create an independently configured FastAPI application."""
    application = FastAPI(
        title="CodePilot API",
        description="Deterministic code intelligence services for CodePilot.",
        version="0.1.0",
    )
    application.include_router(router)
    return application


app = create_app()
