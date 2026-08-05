"""FastAPI application bootstrap."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
from codepilot.repositories.analysis import PostgresAnalysisRepository
from codepilot.services.analysis import AnalysisService, NoopAnalyzer
from codepilot.services.repository_ingestion import (
    IngestionLimits,
    RepositoryIngestionService,
)
from codepilot.worker.analysis_tasks import queue_for_celery


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Dispose only the production repository owned by this application."""
    try:
        yield
    finally:
        if getattr(application.state, "owns_analysis_repository", False):
            repository = getattr(application.state, "analysis_repository", None)
            dispose = getattr(repository, "dispose", None)
            if dispose is not None:
                await dispose()


def create_app(
    settings: Settings | None = None,
    *,
    analysis_service: AnalysisService | None = None,
) -> FastAPI:
    """Create an independently configured FastAPI application."""
    resolved_settings = settings if settings is not None else get_settings()
    configure_logging(resolved_settings)
    application = FastAPI(
        title="CodePilot API",
        description="Deterministic code intelligence services for CodePilot.",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    owns_analysis_repository = analysis_service is None
    analysis_repository: Any
    resolved_analysis_service: AnalysisService
    if owns_analysis_repository:
        analysis_repository = PostgresAnalysisRepository(resolved_settings.database_url_value())
        resolved_analysis_service = AnalysisService(
            analysis_repository,
            RepositoryIngestionService(limits=IngestionLimits.from_settings(resolved_settings)),
            NoopAnalyzer(),
            queue_for_celery(),
            lease_seconds=resolved_settings.analysis_lease_seconds,
        )
    else:
        assert analysis_service is not None
        analysis_repository = getattr(analysis_service, "_repository", None)
        resolved_analysis_service = analysis_service
    application.state.analysis_repository = analysis_repository
    application.state.owns_analysis_repository = owns_analysis_repository
    application.state.analysis_service = resolved_analysis_service
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
