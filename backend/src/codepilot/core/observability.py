"""Optional OpenTelemetry spans and error reporting integration."""

from __future__ import annotations

import logging
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

LOGGER = logging.getLogger(__name__)


def configure_error_reporting(dsn: str | None, environment: str) -> None:
    """Enable Sentry only when an explicit DSN is configured."""
    if not dsn:
        return
    try:
        import sentry_sdk  # type: ignore[import-not-found]
    except ImportError:
        LOGGER.warning("error_reporting_dependency_missing")
        return
    sentry_sdk.init(dsn=dsn, environment=environment, send_default_pii=False)


class OpenTelemetryMiddleware:
    """Create request spans when the optional OpenTelemetry API is installed."""

    def __init__(self, app: ASGIApp, enabled: bool, service_name: str) -> None:
        self.app = app
        self._tracer = _load_tracer(enabled, service_name)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self._tracer is None:
            await self.app(scope, receive, send)
            return
        with self._tracer.start_as_current_span("http.request") as span:
            span.set_attribute("http.method", scope.get("method", ""))
            span.set_attribute("http.route", scope.get("path", ""))
            await self.app(scope, receive, send)


def _load_tracer(enabled: bool, service_name: str) -> Any:
    if not enabled:
        return None
    try:
        from opentelemetry import trace  # type: ignore[import-not-found]
    except ImportError:
        LOGGER.warning("opentelemetry_dependency_missing")
        return None
    return trace.get_tracer(service_name)
