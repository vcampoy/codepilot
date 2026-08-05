"""Small in-process rate limiter suitable for one public MVP instance."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class SlidingWindowRateLimiter:
    """Bound requests per client key with a retry-after value."""

    def __init__(self, requests: int, window_seconds: int) -> None:
        self._requests = requests
        self._window_seconds = window_seconds
        self._events: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        async with self._lock:
            events = self._events[key]
            while events and events[0] <= now - self._window_seconds:
                events.popleft()
            if len(events) >= self._requests:
                retry_after = max(1, int(events[0] + self._window_seconds - now))
                return False, retry_after
            events.append(now)
            return True, 0


class WorkspaceQuota:
    """Bound accepted analyses per workspace for the process lifetime."""

    def __init__(self, max_analyses: int) -> None:
        self._max_analyses = max_analyses
        self._counts: defaultdict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def consume(self, workspace_id: str) -> bool:
        async with self._lock:
            if self._counts[workspace_id] >= self._max_analyses:
                return False
            self._counts[workspace_id] += 1
            return True


class RequestRateLimitMiddleware:
    """Apply an in-process public endpoint limit before route execution."""

    def __init__(self, app: ASGIApp, limiter: SlidingWindowRateLimiter) -> None:
        self.app = app
        self._limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in {"/health", "/health/live"}:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        key = headers.get(b"x-api-key", b"").decode("utf-8", "ignore")
        if not key:
            client = scope.get("client")
            key = client[0] if client else "unknown"
        allowed, retry_after = await self._limiter.allow(key)
        if not allowed:
            response = JSONResponse(
                status_code=429,
                content={"error": {"code": "rate_limit_exceeded", "message": "Too many requests."}},
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
