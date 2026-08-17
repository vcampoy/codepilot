"""Evidence-bounded LLM adapter for Fix jobs."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from importlib import import_module
from typing import Any, cast

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, Field

from codepilot.services.repair import (
    RepairExecutionError,
    RepairGateway,
    RepairRequest,
    RepairResponse,
)

Completion = Callable[..., Awaitable[Any]]


class _RepairOutput(BaseModel):
    patch: str = Field(min_length=1, max_length=512_000)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4_000)


class LiteLlmRepairGateway(RepairGateway):
    """Call the configured workspace model with a strict repair contract."""

    def __init__(
        self,
        configuration_repository: Any,
        encryption_key: str | None,
        *,
        timeout_seconds: float = 120,
        max_tokens: int = 8_192,
        completion: Completion | None = None,
    ) -> None:
        self._repository = configuration_repository
        self._fernet = Fernet(encryption_key.encode()) if encryption_key else None
        self._timeout_seconds = timeout_seconds
        self._max_tokens = max_tokens
        self._completion = completion or self._load_completion()

    async def generate_repair(self, request: RepairRequest) -> RepairResponse:
        configuration = await self._repository.get_llm_configuration(request.workspace_id)
        if (
            configuration is None
            or not configuration.enabled
            or not configuration.encrypted_api_key
        ):
            raise RepairExecutionError("Workspace LLM configuration is unavailable.")
        if self._fernet is None:
            raise RepairExecutionError("LLM encryption is not configured.")
        try:
            api_key = self._fernet.decrypt(configuration.encrypted_api_key.encode()).decode()
        except (InvalidToken, ValueError) as error:
            raise RepairExecutionError("Stored LLM API key could not be decrypted.") from error
        user_prompt = json.dumps(
            {"target_type": request.target_type.value, "target_ids": request.target_ids,
             "rules": request.rules, "evidence": request.evidence},
            ensure_ascii=False,
            default=str,
        )
        kwargs: dict[str, object] = {
            "model": _route_model(configuration.provider, configuration.model),
            "messages": [
                {"role": "system", "content": (
                    "Return only JSON with patch, title, description. Create the smallest "
                    "safe unified diff that fixes only the supplied evidence. Never invent "
                    "findings, paths, secrets, or unrelated changes."
                )},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": self._max_tokens,
            "timeout": self._timeout_seconds,
            "response_format": {"type": "json_object"},
            "api_key": api_key,
        }
        try:
            raw = await asyncio.wait_for(self._completion(**kwargs), self._timeout_seconds)
            content = _completion_content(raw)
            value = _RepairOutput.model_validate_json(content)
        except Exception as error:  # provider SDKs expose incompatible exceptions
            if isinstance(error, RepairExecutionError):
                raise
            raise RepairExecutionError("Repair model returned an invalid response.") from error
        return RepairResponse(value.patch, value.title, value.description)

    @staticmethod
    def _load_completion() -> Completion:
        try:
            litellm = import_module("litellm")
        except ImportError as error:
            raise RepairExecutionError("LiteLLM is not installed for Fix execution.") from error
        return cast(Completion, litellm.acompletion)


def _completion_content(raw: Any) -> str:
    choices = getattr(raw, "choices", None)
    if not choices and isinstance(raw, dict):
        choices = raw.get("choices")
    if not choices:
        raise ValueError("Completion contains no choices")
    first = choices[0]
    message = getattr(first, "message", None)
    if message is None and isinstance(first, dict):
        message = first.get("message")
    content = getattr(message, "content", None) if message is not None else None
    if content is None and isinstance(message, dict):
        content = message.get("content")
    if not isinstance(content, str):
        raise ValueError("Completion contains no text")
    return content


def _route_model(provider: str, model: str) -> str:
    prefix = {"google": "gemini", "grok": "xai", "nvidia": "nvidia_nim"}.get(provider, provider)
    return model if model.startswith(f"{prefix}/") else f"{prefix}/{model}"
