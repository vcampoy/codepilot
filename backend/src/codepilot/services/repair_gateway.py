"""Evidence-bounded LLM adapter for Fix jobs."""

from __future__ import annotations

import asyncio
import json
import logging
import re
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
logger = logging.getLogger(__name__)


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
            {
                "target_type": request.target_type.value,
                "target_ids": request.target_ids,
                "rules": request.rules,
                "evidence": request.evidence,
            },
            ensure_ascii=False,
            default=str,
        )
        kwargs: dict[str, object] = {
            "model": _route_model(configuration.provider, configuration.model),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only JSON with patch, title, description. Create the smallest "
                        "safe unified diff that fixes only the supplied evidence. Never invent "
                        "findings, paths, secrets, or unrelated changes."
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": self._max_tokens,
            "timeout": self._timeout_seconds,
            "response_format": {"type": "json_object"},
            "api_key": api_key,
        }
        try:
            raw = await asyncio.wait_for(self._completion(**kwargs), self._timeout_seconds)
        except Exception as error:  # provider SDKs expose incompatible exceptions
            category, message = _provider_failure(error)
            logger.warning(
                "Repair provider request failed",
                extra={
                    "category": category,
                    "provider": configuration.provider,
                    "model": configuration.model,
                    "job_id": getattr(request, "job_id", None),
                },
            )
            raise RepairExecutionError(message) from error
        try:
            content = _completion_content(raw)
            value = _RepairOutput.model_validate_json(content)
        except Exception as error:  # malformed provider output is a contract failure
            logger.warning(
                "Repair provider returned malformed output",
                extra={
                    "category": "invalid_response",
                    "provider": configuration.provider,
                    "model": configuration.model,
                    "job_id": getattr(request, "job_id", None),
                },
            )
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


def _provider_failure(error: Exception) -> tuple[str, str]:
    """Map provider SDK failures to safe, actionable messages.

    SDK exception text may contain API keys, request bodies, or account details;
    callers receive only a stable category message and logs contain no raw error.
    """
    status_code = _status_code(error)
    class_name = type(error).__name__.lower()
    detail = str(error).lower()
    if _is_timeout(error, class_name, detail):
        return "timeout", "Repair provider timed out."
    if _is_rate_limit(status_code, class_name, detail):
        return "rate_limit", "Repair provider quota or rate limit exceeded."
    if _is_authentication(status_code, class_name, detail):
        return "authentication", "Repair provider authentication failed."
    if _is_unavailable(error, class_name, detail):
        return "unavailable", "Repair provider is unavailable."
    return "provider_error", "Repair provider request failed."


def _has_marker(value: str, markers: tuple[str, ...]) -> bool:
    return any(marker in value for marker in markers)


def _is_timeout(error: Exception, class_name: str, detail: str) -> bool:
    return isinstance(error, (asyncio.TimeoutError, TimeoutError)) or _has_marker(
        class_name + detail, ("timeout", "timed out")
    )


def _is_rate_limit(status_code: int | None, class_name: str, detail: str) -> bool:
    return status_code == 429 or _has_marker(
        class_name + detail, ("ratelimit", "rate limit", "quota")
    )


def _is_authentication(status_code: int | None, class_name: str, detail: str) -> bool:
    return status_code in {401, 403} or _has_marker(
        class_name + detail, ("authentication", "unauthorized")
    )


def _is_unavailable(error: Exception, class_name: str, detail: str) -> bool:
    return isinstance(error, (ConnectionError, OSError)) or _has_marker(
        class_name + detail, ("unavailable", "connection", "serviceunavailable")
    )


def _status_code(error: Exception) -> int | None:
    candidate = getattr(error, "status_code", None)
    if candidate is None:
        response = getattr(error, "response", None)
        candidate = getattr(response, "status_code", None)
    return candidate if isinstance(candidate, int) else _status_from_message(str(error))


def _status_from_message(message: str) -> int | None:
    match = re.search(r"\b(401|403|429)\b", message)
    return int(match.group(1)) if match else None
