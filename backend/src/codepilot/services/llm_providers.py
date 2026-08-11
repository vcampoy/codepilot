"""Fixed-provider model discovery and credential validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx


@dataclass(frozen=True, slots=True)
class LlmProvider:
    id: str
    label: str
    preferred_model: str


PROVIDERS = (
    LlmProvider("openai", "OpenAI", "gpt-5-mini"),
    LlmProvider("anthropic", "Anthropic", "claude-sonnet-5"),
    LlmProvider("openrouter", "OpenRouter", "openai/gpt-5-mini"),
    LlmProvider("google", "Google", "gemini-3.6-flash"),
    LlmProvider("kimi", "Kimi", "kimi-k3"),
    LlmProvider("grok", "Grok", "grok-4.5"),
    LlmProvider("minimax", "MiniMax", "MiniMax-M2.7"),
    LlmProvider("nvidia", "NVIDIA", "nvidia/nemotron-3-nano-30b-a3b"),
    LlmProvider("deepseek", "DeepSeek", "deepseek-v4-flash"),
)
_BY_ID = {item.id: item for item in PROVIDERS}
_MAX_BODY = 1 << 20
_MAX_MODELS = 1000
_NON_CHAT_MARKERS = ("embedding", "moderation", "whisper", "tts", "dall-e", "rerank", "image")


class ProviderDiscovery(Protocol):
    async def discover(self, provider: str, api_key: str) -> list[str]: ...


class ProviderDiscoveryError(RuntimeError):
    """Transient upstream or malformed provider response."""


class InvalidProviderCredentials(ValueError):
    """Provider rejected the supplied credential."""


class HttpxProviderDiscovery:
    """Provider adapter with fixed URLs (no user-controlled network targets)."""

    async def discover(self, provider: str, api_key: str) -> list[str]:
        if provider not in _BY_ID:
            raise ValueError("unsupported provider")
        timeout = httpx.Timeout(10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            if provider == "openrouter":
                await self._request(client, "https://openrouter.ai/api/v1/key", api_key)
                response = await self._request(
                    client, "https://openrouter.ai/api/v1/models", api_key
                )
            elif provider == "google":
                response = await self._request(
                    client,
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    api_key,
                    query={"key": api_key},
                    auth=False,
                )
            elif provider == "anthropic":
                response = await self._request(
                    client,
                    "https://api.anthropic.com/v1/models",
                    api_key,
                    headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                    auth=False,
                )
            elif provider == "kimi":
                response = await self._request(client, "https://api.moonshot.ai/v1/models", api_key)
            elif provider == "grok":
                response = await self._request(client, "https://api.x.ai/v1/models", api_key)
            elif provider == "minimax":
                response = await self._request(client, "https://api.minimax.io/v1/models", api_key)
            elif provider == "nvidia":
                response = await self._request(
                    client, "https://integrate.api.nvidia.com/v1/models", api_key
                )
                await self._validate_nvidia(client, api_key)
            elif provider == "deepseek":
                response = await self._request(client, "https://api.deepseek.com/models", api_key)
            else:
                response = await self._request(client, "https://api.openai.com/v1/models", api_key)
        return _models_from_payload(response, provider)

    async def _validate_nvidia(self, client: httpx.AsyncClient, key: str) -> None:
        response = await client.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": _BY_ID["nvidia"].preferred_model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
        )
        _raise_for_status(response)

    async def _request(
        self,
        client: httpx.AsyncClient,
        url: str,
        key: str,
        *,
        query: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        auth: bool = True,
    ) -> Any:
        request_headers = dict(headers or {})
        if auth:
            request_headers["Authorization"] = f"Bearer {key}"
        response = await client.get(url, headers=request_headers, params=query)
        _raise_for_status(response)
        if len(response.content) > _MAX_BODY:
            raise ProviderDiscoveryError("provider response exceeds size limit")
        try:
            return response.json()
        except ValueError as error:
            raise ProviderDiscoveryError("provider returned invalid JSON") from error


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code in (401, 403):
        raise InvalidProviderCredentials("provider rejected API key")
    if response.status_code == 429 or response.status_code >= 500:
        raise ProviderDiscoveryError("provider temporarily unavailable")
    if response.status_code >= 400:
        raise ProviderDiscoveryError("provider request failed")


def _models_from_payload(payload: Any, provider: str) -> list[str]:
    values = payload.get("models", payload.get("data", [])) if isinstance(payload, dict) else []
    items = values if isinstance(values, list) else []
    models = (_normalize_model(item, provider) for item in items)
    return sorted({model for model in models if model})[:_MAX_MODELS]


def _normalize_model(item: Any, provider: str) -> str | None:
    model = _model_name(item)
    if not model or not _supports_chat(item, provider) or _is_non_chat(model):
        return None
    return model.removeprefix("models/")


def _model_name(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("id") or item.get("name") or "")
    return ""


def _supports_chat(item: Any, provider: str) -> bool:
    if provider != "google":
        return True
    return isinstance(item, dict) and "generateContent" in (
        item.get("supportedGenerationMethods") or []
    )


def _is_non_chat(model: str) -> bool:
    return any(marker in model.lower() for marker in _NON_CHAT_MARKERS)


def provider_catalog() -> list[dict[str, str]]:
    return [{"id": item.id, "label": item.label} for item in PROVIDERS]


def preferred_model(provider: str) -> str:
    return _BY_ID[provider].preferred_model
