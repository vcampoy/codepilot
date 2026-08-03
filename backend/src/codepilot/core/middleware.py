"""Request correlation and access logging middleware."""

import re
from time import perf_counter
from uuid import uuid4

import structlog
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CORRELATION_HEADER = "X-Correlation-ID"
_VALID_CORRELATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
logger = structlog.get_logger(__name__)


def _correlation_id(value: str | None) -> str:
    return value if value and _VALID_CORRELATION_ID.fullmatch(value) else str(uuid4())


def _decode_correlation_id(value: bytes) -> str | None:
    try:
        return value.decode("ascii")
    except UnicodeDecodeError:
        return None


class CorrelationMiddleware:
    """Bind a bounded correlation ID and add it to every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        incoming = _decode_correlation_id(headers.get(b"x-correlation-id", b""))
        correlation_id = _correlation_id(incoming)
        scope.setdefault("state", {})["correlation_id"] = correlation_id
        previous_context = structlog.contextvars.get_contextvars()
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
        started = perf_counter()
        response_status = 0
        response_started = False

        async def send_with_correlation(message: Message) -> None:
            nonlocal response_started, response_status
            if message["type"] == "http.response.start":
                response_started = True
                response_status = int(message["status"])
                message["headers"] = [
                    *message.get("headers", []),
                    (CORRELATION_HEADER.lower().encode(), correlation_id.encode()),
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_with_correlation)
        except Exception:
            if response_started:
                raise
            response = JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "internal_server_error",
                        "message": "An unexpected error occurred.",
                        "correlation_id": correlation_id,
                    }
                },
            )
            await response(scope, receive, send_with_correlation)
        finally:
            if response_status:
                logger.info(
                    "request.completed",
                    method=scope.get("method", ""),
                    path=scope.get("path", ""),
                    status=response_status,
                    duration_ms=round((perf_counter() - started) * 1000, 2),
                )
            structlog.contextvars.clear_contextvars()
            structlog.contextvars.bind_contextvars(**previous_context)
