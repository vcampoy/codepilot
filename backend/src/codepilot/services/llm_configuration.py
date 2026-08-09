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


class LlmConfigurationRepository(Protocol):
    async def get_llm_configuration(self, workspace_id: str) -> LlmConfiguration | None: ...

    async def save_llm_configuration(self, configuration: LlmConfiguration) -> LlmConfiguration: ...


class LlmConfigurationService:
    """Keep provider secrets encrypted at rest and out of response models."""

    def __init__(self, repository: LlmConfigurationRepository, encryption_key: str | None) -> None:
        self._repository = repository
        self._fernet = Fernet(encryption_key.encode()) if encryption_key else None

    async def get(self, workspace_id: str) -> LlmConfigurationView:
        configuration = await self._repository.get_llm_configuration(workspace_id)
        if configuration is None:
            return LlmConfigurationView(False, DEFAULT_PROVIDER, DEFAULT_MODEL, False)
        return LlmConfigurationView(
            configuration.enabled,
            configuration.provider,
            configuration.model,
            configuration.api_key_configured,
        )

    async def save(
        self,
        workspace_id: str,
        *,
        enabled: bool,
        provider: str,
        model: str,
        api_key: str | None,
    ) -> LlmConfigurationView:
        provider, model = self._normalize_llm_input(provider, model)
        current = await self._repository.get_llm_configuration(workspace_id)
        encrypted = self._resolve_encrypted_key(
            current.encrypted_api_key if current else None, api_key
        )
        if enabled and not encrypted:
            raise ValueError("an API key is required when LLM enrichment is enabled")
        saved = LlmConfiguration(
            workspace_id, enabled, provider, model, encrypted, datetime.now(UTC)
        )
        await self._repository.save_llm_configuration(saved)
        return await self.get(workspace_id)

    @staticmethod
    def _normalize_llm_input(provider: str, model: str) -> tuple[str, str]:
        normalized_provider = provider.strip().lower()
        normalized_model = model.strip()
        if not normalized_provider or len(normalized_provider) > 128:
            raise ValueError("provider must be between 1 and 128 characters")
        if not normalized_model or len(normalized_model) > 256:
            raise ValueError("model must be between 1 and 256 characters")
        return normalized_provider, normalized_model

    def _resolve_encrypted_key(self, current: str | None, api_key: str | None) -> str | None:
        if api_key is None:
            return current
        stripped = api_key.strip()
        if not stripped:
            return None
        if self._fernet is None:
            raise RuntimeError("LLM_CONFIG_ENCRYPTION_KEY is required to store an API key")
        return self._fernet.encrypt(stripped.encode()).decode()

    async def gateway(self, workspace_id: str) -> LlmGateway | None:
        configuration = await self._repository.get_llm_configuration(workspace_id)
        if configuration is None:
            return None
        if not configuration.enabled:
            return NoOpLlmGateway()
        if self._fernet is None or not configuration.encrypted_api_key:
            return NoOpLlmGateway()
        try:
            api_key = self._fernet.decrypt(configuration.encrypted_api_key.encode()).decode()
        except (InvalidToken, ValueError) as error:
            raise RuntimeError("stored LLM API key could not be decrypted") from error
        return LiteLlmGateway(
            provider=configuration.provider,
            model=configuration.model,
            api_key=api_key,
        )
