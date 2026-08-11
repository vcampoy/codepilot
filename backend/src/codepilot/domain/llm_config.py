"""Workspace-scoped configuration for optional LLM enrichment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

DEFAULT_PROVIDER: Final[str] = "openai"
DEFAULT_MODEL: Final[str] = "gpt-4o-mini"


@dataclass(frozen=True, slots=True)
class LlmConfiguration:
    """Persisted provider settings; the API key never leaves this boundary."""

    workspace_id: str
    enabled: bool
    provider: str
    model: str
    encrypted_api_key: str | None
    updated_at: datetime
    available_models: tuple[str, ...] = ()

    @property
    def api_key_configured(self) -> bool:
        return bool(self.encrypted_api_key)


@dataclass(frozen=True, slots=True)
class LlmConfigurationView:
    """Safe public representation that intentionally omits the secret."""

    enabled: bool
    provider: str
    model: str
    api_key_configured: bool
    available_models: tuple[str, ...] = ()
