"""Validation, encryption, and gateway construction for workspace LLM settings."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken

from codepilot.domain.llm_config import (
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    LlmConfiguration,
    LlmConfigurationView,
)
from codepilot.llm.contracts import NoOpLlmGateway
from codepilot.llm.gateway import LiteLlmGateway
from codepilot.services.llm_enrichment import LlmGateway
from codepilot.services.llm_providers import (
    PROVIDERS,
    HttpxProviderDiscovery,
    InvalidProviderCredentials,
    ProviderDiscovery,
    preferred_model,
)


class LlmConfigurationRepository(Protocol):
    async def get_llm_configuration(self, workspace_id: str) -> LlmConfiguration | None: ...

    async def save_llm_configuration(self, configuration: LlmConfiguration) -> LlmConfiguration: ...


class LlmConfigurationService:
    """Keep provider secrets encrypted at rest and out of response models."""

    def __init__(
        self,
        repository: LlmConfigurationRepository,
        encryption_key: str | None,
        discovery: ProviderDiscovery | None = None,
    ) -> None:
        self._repository = repository
        self._fernet = Fernet(encryption_key.encode()) if encryption_key else None
        self._discovery = discovery or HttpxProviderDiscovery()

    async def get(self, workspace_id: str) -> LlmConfigurationView:
        configuration = await self._repository.get_llm_configuration(workspace_id)
        if configuration is None:
            return LlmConfigurationView(
                False, DEFAULT_PROVIDER, DEFAULT_MODEL, False, (DEFAULT_MODEL,)
            )
        return LlmConfigurationView(
            configuration.enabled,
            configuration.provider,
            configuration.model,
            configuration.api_key_configured,
            configuration.available_models or (configuration.model,),
        )

    async def save(
        self,
        workspace_id: str,
        *,
        enabled: bool,
        provider: str,
        model: str | None,
        api_key: str | None,
    ) -> LlmConfigurationView:
        provider = _normalize_provider(provider)
        current = await self._repository.get_llm_configuration(workspace_id)
        encrypted = self._resolve_key(current, provider, api_key)
        requested = model.strip() if model else ""
        selected, models = await self._resolve_model(
            enabled, provider, current, requested, encrypted
        )
        saved = LlmConfiguration(
            workspace_id, enabled, provider, selected, encrypted, datetime.now(UTC), tuple(models)
        )
        await self._repository.save_llm_configuration(saved)
        return await self.get(workspace_id)

    async def _resolve_model(
        self,
        enabled: bool,
        provider: str,
        current: LlmConfiguration | None,
        requested: str,
        encrypted: str | None,
    ) -> tuple[str, list[str]]:
        same_provider = current is not None and current.provider == provider
        current_model = current.model if current is not None and same_provider else ""
        if not enabled:
            return self._disabled_model(requested, current_model, current, same_provider)
        if not encrypted:
            raise ValueError("an API key is required when LLM enrichment is enabled")
        models = await self._discover(provider, self._decrypt(encrypted))
        selected = _select_model(requested, current_model, models, preferred_model(provider))
        return selected, models

    @staticmethod
    def _disabled_model(
        requested: str, current_model: str, current: LlmConfiguration | None, same_provider: bool
    ) -> tuple[str, list[str]]:
        return _fallback_model(requested, current_model), _stored_models(current, same_provider)

    async def _discover(self, provider: str, key: str) -> list[str]:
        try:
            models = await self._discovery.discover(provider, key)
        except InvalidProviderCredentials:
            raise
        except ValueError:
            raise
        except Exception as error:
            raise RuntimeError("LLM provider unavailable") from error
        if not models:
            raise ValueError("provider returned no conversational models")
        return models

    def _resolve_key(
        self, current: LlmConfiguration | None, provider: str, api_key: str | None
    ) -> str | None:
        same_provider = current is not None and current.provider == provider
        if current and not same_provider and not (api_key and api_key.strip()):
            raise ValueError("a new API key is required when changing provider")
        existing_key = current.encrypted_api_key if current is not None and same_provider else None
        return self._resolve_encrypted_key(existing_key, api_key)

    def _resolve_encrypted_key(self, current: str | None, api_key: str | None) -> str | None:
        if api_key is None:
            return current
        stripped = api_key.strip()
        if not stripped:
            return None
        if self._fernet is None:
            raise RuntimeError("LLM_CONFIG_ENCRYPTION_KEY is required to store an API key")
        return self._fernet.encrypt(stripped.encode()).decode()

    def _decrypt(self, encrypted: str | None) -> str:
        if not encrypted or self._fernet is None:
            raise ValueError("LLM_CONFIG_ENCRYPTION_KEY is required")
        try:
            return self._fernet.decrypt(encrypted.encode()).decode()
        except (InvalidToken, ValueError) as error:
            raise RuntimeError("stored LLM API key could not be decrypted") from error

    async def gateway(self, workspace_id: str) -> LlmGateway | None:
        configuration = await self._repository.get_llm_configuration(workspace_id)
        return self._gateway_for_configuration(configuration)

    def _gateway_for_configuration(
        self, configuration: LlmConfiguration | None
    ) -> LlmGateway | None:
        if configuration is None or not configuration.enabled:
            return None if configuration is None else NoOpLlmGateway()
        if self._fernet is None or not configuration.encrypted_api_key:
            return NoOpLlmGateway()
        prefix, base_url = _litellm_route(configuration.provider, configuration.model)
        return LiteLlmGateway(
            provider=prefix,
            metadata_provider=configuration.provider,
            model=configuration.model,
            api_key=self._decrypt(configuration.encrypted_api_key),
            base_url=base_url,
        )


def _select_model(requested: str, current: str, models: list[str], preferred: str) -> str:
    if requested in models:
        return requested
    if current in models:
        return current
    if preferred in models:
        return preferred
    return sorted(models)[0]


def _fallback_model(requested: str, current: str) -> str:
    return requested or current or DEFAULT_MODEL


def _stored_models(current: LlmConfiguration | None, same_provider: bool) -> list[str]:
    return list(current.available_models) if current is not None and same_provider else []


def _normalize_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized not in {item.id for item in PROVIDERS}:
        raise ValueError("unsupported provider")
    return normalized


def _litellm_route(provider: str, model: str) -> tuple[str, str | None]:
    routes = {
        "openai": ("openai", None),
        "anthropic": ("anthropic", None),
        "openrouter": ("openrouter", None),
        "google": ("gemini", None),
        "grok": ("xai", None),
        "nvidia": ("nvidia_nim", "https://integrate.api.nvidia.com/v1"),
        "deepseek": ("deepseek", None),
        "kimi": ("openai", "https://api.moonshot.ai/v1"),
        "minimax": ("openai", "https://api.minimax.io/v1"),
    }
    return routes.get(provider, (provider, None))
