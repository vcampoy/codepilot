"""Workspace LLM configuration endpoints."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from codepilot.core.auth import authenticate
from codepilot.core.errors import ApplicationError
from codepilot.domain.llm_config import LlmConfigurationView
from codepilot.services.llm_configuration import LlmConfigurationService

router = APIRouter(prefix="/settings/llm", tags=["llm"])


class LlmConfigurationPayload(BaseModel):
    enabled: bool = False
    provider: str = Field(default="openai", min_length=1, max_length=128)
    model: str = Field(default="gpt-4o-mini", min_length=1, max_length=256)
    # Omitted means preserve the current key; an empty value explicitly removes it.
    api_key: str | None = Field(default=None, max_length=4096)


class LlmConfigurationResponse(BaseModel):
    enabled: bool
    provider: str
    model: str
    api_key_configured: bool


@router.get("", response_model=LlmConfigurationResponse)
async def get_llm_configuration(request: Request) -> LlmConfigurationResponse:
    identity = authenticate(request)
    service = _service(request)
    return _response(await service.get(identity.workspace_id))


@router.put("", response_model=LlmConfigurationResponse)
async def save_llm_configuration(
    payload: LlmConfigurationPayload, request: Request
) -> LlmConfigurationResponse:
    identity = authenticate(request)
    service = _service(request)
    try:
        saved = await service.save(
            identity.workspace_id,
            enabled=payload.enabled,
            provider=payload.provider,
            model=payload.model,
            api_key=payload.api_key,
        )
    except ValueError as error:
        raise ApplicationError("invalid_llm_configuration", str(error), status_code=400) from error
    except RuntimeError as error:
        raise ApplicationError(
            "llm_configuration_unavailable", str(error), status_code=503
        ) from error
    return _response(saved)


def _service(request: Request) -> LlmConfigurationService:
    return cast(LlmConfigurationService, request.app.state.llm_configuration_service)


def _response(value: LlmConfigurationView) -> LlmConfigurationResponse:
    return LlmConfigurationResponse(
        enabled=value.enabled,
        provider=value.provider,
        model=value.model,
        api_key_configured=value.api_key_configured,
    )
