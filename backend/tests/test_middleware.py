import asyncio
from typing import cast

import pytest
import structlog
from starlette.types import Message, Receive, Scope, Send

from codepilot.core.middleware import CorrelationMiddleware


def _scope(headers: list[tuple[bytes, bytes]] | None = None) -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": "GET",
        "path": "/test",
        "headers": headers or [],
    }


async def _receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


def test_non_ascii_correlation_header_is_replaced() -> None:
    messages: list[Message] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def send(message: Message) -> None:
        messages.append(message)

    asyncio.run(
        CorrelationMiddleware(app)(_scope([(b"x-correlation-id", b"valid\xff")]), _receive, send)
    )

    header = dict(cast(list[tuple[bytes, bytes]], messages[0]["headers"]))[b"x-correlation-id"]
    assert header != b"valid"
    assert len(header) == 36


def test_exception_after_response_start_propagates() -> None:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("after start")

    with pytest.raises(RuntimeError, match="after start"):
        asyncio.run(CorrelationMiddleware(app)(_scope(), _receive, _send))


async def _send(message: Message) -> None:
    return None


def test_outer_structlog_context_is_restored_without_correlation_leak() -> None:
    seen: dict[str, object] = {}

    async def exercise() -> None:
        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            seen.update(structlog.contextvars.get_contextvars())
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(outer="retained")
        await CorrelationMiddleware(app)(_scope(), _receive, _send)

        assert "correlation_id" in seen
        assert structlog.contextvars.get_contextvars() == {"outer": "retained"}
        structlog.contextvars.clear_contextvars()

    asyncio.run(exercise())
