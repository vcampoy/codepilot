"""FastAPI application bootstrap."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from codepilot.analyzers.risk_score import QualityGateConfig
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
from codepilot.core.observability import OpenTelemetryMiddleware, configure_error_reporting
from codepilot.core.rate_limit import (
    RequestRateLimitMiddleware,
    SlidingWindowRateLimiter,
    WorkspaceQuota,
)
from codepilot.core.security import SecurityHeadersMiddleware
from codepilot.core.settings import Settings, get_settings
from codepilot.github.contracts import GitHubWebhookEvent
from codepilot.github.webhooks import GitHubWebhookService, InMemoryWebhookEventStore
from codepilot.llm.contracts import EnrichmentTask, NoOpLlmGateway
from codepilot.llm.gateway import LiteLlmGateway
from codepilot.repositories.analysis import PostgresAnalysisRepository
from codepilot.services.analysis import AnalysisService, NoopAnalyzer
from codepilot.services.llm_configuration import LlmConfigurationService
from codepilot.services.llm_enrichment import LlmEnrichmentService, LlmGateway
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
    llm_gateway: LlmGateway | None = None,
    github_webhook_service: GitHubWebhookService | None = None,
) -> FastAPI:
    """Create an independently configured FastAPI application."""
    resolved_settings = settings if settings is not None else get_settings()
    configure_logging(resolved_settings)
    configure_error_reporting(
        resolved_settings.error_reporting_dsn_value(), resolved_settings.environment
    )
    application = FastAPI(
        title="CodePilot API",
        description="Deterministic code intelligence services for CodePilot.",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    rate_limiter = SlidingWindowRateLimiter(
        resolved_settings.rate_limit_requests,
        resolved_settings.rate_limit_window_seconds,
    )
    application.state.rate_limiter = rate_limiter
    application.state.workspace_quota = WorkspaceQuota(resolved_settings.workspace_analysis_quota)
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
            quality_gate_config=QualityGateConfig(
                max_new_critical_findings=resolved_settings.quality_gate_max_new_critical_findings,
                max_risk_score=resolved_settings.quality_gate_max_risk_score,
                max_new_hotspots=resolved_settings.quality_gate_max_new_hotspots,
            ),
        )
    else:
        assert analysis_service is not None
        analysis_repository = getattr(analysis_service, "_repository", None)
        resolved_analysis_service = analysis_service
    application.state.analysis_repository = analysis_repository
    application.state.owns_analysis_repository = owns_analysis_repository
    application.state.analysis_service = resolved_analysis_service
    resolved_llm_gateway = llm_gateway or _build_llm_gateway(resolved_settings)
    application.state.llm_enrichment_service = LlmEnrichmentService(
        resolved_llm_gateway, analysis_repository
    )
    application.state.llm_configuration_service = LlmConfigurationService(
        analysis_repository, resolved_settings.llm_config_encryption_key_value()
    )
    application.state.github_webhook_service = github_webhook_service or (
        _build_github_webhook_service(resolved_settings)
    )
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
    application.add_middleware(RequestRateLimitMiddleware, limiter=rate_limiter)
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(
        OpenTelemetryMiddleware,
        enabled=resolved_settings.observability_enabled,
        service_name=resolved_settings.otel_service_name,
    )
    return application


def _build_llm_gateway(settings: Settings) -> LlmGateway:
    if not settings.llm_enabled:
        return NoOpLlmGateway()
    if not settings.llm_model:
        return NoOpLlmGateway()
    models_by_task = {
        task: (model,)
        for task, model in (
            (EnrichmentTask.FILE_RISK, settings.llm_model_file_risk),
            (EnrichmentTask.REFACTORING_PLAN, settings.llm_model_refactoring_plan),
            (EnrichmentTask.DETERMINISTIC_SUMMARY, settings.llm_model_deterministic_summary),
        )
        if model
    }
    return LiteLlmGateway(
        model=settings.llm_model,
        fallback_models=settings.llm_fallback_models,
        api_key=settings.llm_api_key_value(),
        provider=settings.llm_provider or "litellm",
        timeout_seconds=settings.llm_timeout_seconds,
        max_tokens=settings.llm_max_tokens,
        models_by_task=models_by_task,
    )


def _build_github_webhook_service(settings: Settings) -> GitHubWebhookService | None:
    secret = settings.github_webhook_secret_value()
    if not settings.github_enabled or not secret:
        return None

    async def dispatch(_event: GitHubWebhookEvent) -> None:
        return None

    return GitHubWebhookService(secret.encode(), InMemoryWebhookEventStore(), dispatch)


app = create_app()
