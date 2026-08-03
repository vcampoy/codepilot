"""FastAPI application bootstrap."""

from typing import Any, cast

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from codepilot.api.router import router
from codepilot.core.errors import (
    ApplicationError,
    application_exception_handler,
    http_exception_handler,
    unexpected_exception_handler,
    validation_exception_handler,
)
from codepilot.core.logging import configure_logging
from codepilot.core.middleware import CorrelationMiddleware
from codepilot.core.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an independently configured FastAPI application."""
    resolved_settings = settings if settings is not None else get_settings()
    configure_logging(resolved_settings)
    application = FastAPI(
        title="CodePilot API",
        description="Deterministic code intelligence services for CodePilot.",
        version="0.1.0",
    )
    application.state.settings = resolved_settings
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-ID"],
    )
    application.add_middleware(CorrelationMiddleware)
    application.add_exception_handler(
        RequestValidationError, cast(Any, validation_exception_handler)
    )
    application.add_exception_handler(ApplicationError, cast(Any, application_exception_handler))
    application.add_exception_handler(StarletteHTTPException, cast(Any, http_exception_handler))
    application.add_exception_handler(Exception, unexpected_exception_handler)
    application.include_router(router)
    return application


app = create_app()
