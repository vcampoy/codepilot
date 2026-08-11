from __future__ import annotations

import asyncio
from typing import Any, cast

import httpx
import pytest

from codepilot.services.llm_providers import (
    PROVIDERS,
    HttpxProviderDiscovery,
    InvalidProviderCredentials,
    ProviderDiscoveryError,
    _models_from_payload,
    provider_catalog,
)


def test_catalog_contains_exactly_supported_providers() -> None:
    assert [item["id"] for item in provider_catalog()] == [item.id for item in PROVIDERS]
    assert len(PROVIDERS) == 9


def test_openrouter_validates_key_then_discovers_models(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"limit": 1}})
        return httpx.Response(
            200, json={"data": [{"id": "openai/gpt-5-mini"}, {"id": "x-embedding"}]}
        )

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", cast(Any, client))
    models = asyncio.run(HttpxProviderDiscovery().discover("openrouter", "secret"))
    assert models == ["openai/gpt-5-mini"]
    assert calls[0].url.path == "/api/v1/key"
    assert calls[0].headers["authorization"] == "Bearer secret"


def test_google_filtering_deduplicates_normalizes_and_limits() -> None:
    payload = {
        "models": [
            {"name": "models/gemini-a", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-a", "supportedGenerationMethods": ["generateContent"]},
            {"id": "embedding-a", "supportedGenerationMethods": ["generateContent"]},
        ]
    }
    assert _models_from_payload(payload, "google") == ["gemini-a"]


def test_invalid_credentials_and_transient_errors_are_classified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    original = httpx.AsyncClient

    def client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return original(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "AsyncClient", cast(Any, client))
    with pytest.raises(InvalidProviderCredentials):
        asyncio.run(HttpxProviderDiscovery().discover("openai", "bad"))

    with pytest.raises(ProviderDiscoveryError):
        from codepilot.services.llm_providers import _raise_for_status

        _raise_for_status(httpx.Response(503))
