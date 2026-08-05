"""Signed, idempotent GitHub webhook handling."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Awaitable, Callable
from typing import Protocol

from codepilot.github.contracts import GitHubWebhookEvent, WebhookProcessingResult


class InvalidWebhookSignatureError(Exception):
    """The webhook signature is missing or invalid."""


class WebhookEventStore(Protocol):
    """Atomic delivery-id claim boundary."""

    async def claim(self, delivery_id: str) -> bool: ...

    async def release(self, delivery_id: str) -> None: ...


class InMemoryWebhookEventStore:
    """Deterministic event store for tests and single-process development."""

    def __init__(self) -> None:
        self._claimed: set[str] = set()

    async def claim(self, delivery_id: str) -> bool:
        if delivery_id in self._claimed:
            return False
        self._claimed.add(delivery_id)
        return True

    async def release(self, delivery_id: str) -> None:
        self._claimed.discard(delivery_id)


class GitHubWebhookService:
    """Verify, normalize, and dispatch supported GitHub events exactly once."""

    def __init__(
        self,
        secret: bytes,
        event_store: WebhookEventStore,
        dispatch: Callable[[GitHubWebhookEvent], Awaitable[None] | None],
    ) -> None:
        if not secret:
            raise ValueError("webhook secret is required")
        self._secret = secret
        self._event_store = event_store
        self._dispatch = dispatch

    async def handle(
        self,
        *,
        event_name: str,
        delivery_id: str,
        signature: str,
        body: bytes,
    ) -> WebhookProcessingResult:
        verify_signature(self._secret, body, signature)
        event = _parse_event(event_name, delivery_id, body)
        if event is None:
            return WebhookProcessingResult(accepted=False, duplicate=False)
        if not await self._event_store.claim(delivery_id):
            return WebhookProcessingResult(accepted=True, duplicate=True, event=event)
        try:
            result = self._dispatch(event)
            if result is not None:
                await result
        except Exception:
            await self._event_store.release(delivery_id)
            raise
        return WebhookProcessingResult(accepted=True, duplicate=False, event=event)


def verify_signature(secret: bytes, body: bytes, signature: str) -> None:
    """Verify GitHub's HMAC SHA-256 signature with constant-time comparison."""
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise InvalidWebhookSignatureError


def _parse_event(
    event_name: str, delivery_id: str, body: bytes
) -> GitHubWebhookEvent | None:
    if event_name not in {"push", "pull_request"}:
        return None
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidWebhookSignatureError("Webhook body is not valid JSON.") from error
    repository = payload.get("repository", {}).get("full_name")
    installation_id = payload.get("installation", {}).get("id")
    if not isinstance(repository, str):
        raise InvalidWebhookSignatureError("Webhook repository is missing.")
    if event_name == "push":
        return GitHubWebhookEvent(
            delivery_id=delivery_id,
            event_name="push",
            repository=repository,
            installation_id=installation_id,
            before_sha=payload.get("before"),
            after_sha=payload.get("after"),
        )
    action = payload.get("action")
    if action not in {"opened", "synchronize", "reopened"}:
        return None
    pull_request = payload.get("pull_request", {})
    return GitHubWebhookEvent(
        delivery_id=delivery_id,
        event_name="pull_request",
        action=action,
        repository=repository,
        installation_id=installation_id,
        pull_request_number=pull_request.get("number"),
        before_sha=pull_request.get("base", {}).get("sha"),
        after_sha=pull_request.get("head", {}).get("sha"),
    )
