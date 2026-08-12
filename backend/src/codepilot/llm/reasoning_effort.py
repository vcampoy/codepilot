"""Resolve model-specific LiteLLM reasoning effort values."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from importlib import import_module
from typing import Any, cast

SUPPORTED_BASE = ("low", "medium", "high")
_EXPLICIT_FLAGS = {
    "none": "supports_none_reasoning_effort",
    "minimal": "supports_minimal_reasoning_effort",
    "xhigh": "supports_xhigh_reasoning_effort",
    "max": "supports_max_reasoning_effort",
}

Lookup = Callable[[str], Any | Awaitable[Any]]


class ReasoningEffortResolver:
    """Fail-closed, injectable resolver for model effort capabilities."""

    def __init__(
        self,
        *,
        supported_params: Lookup | None = None,
        model_info: Lookup | None = None,
    ) -> None:
        self._supported_params = supported_params
        self._model_info = model_info

    async def for_model(self, model: str) -> list[str]:
        try:
            params = await _resolve(self._supported_params or _default_supported_params, model)
            if not params or "reasoning_effort" not in params:
                return []
            info = await _resolve(self._model_info or _default_model_info, model)
            return _efforts(info if isinstance(info, Mapping) else {})
        except Exception:  # noqa: BLE001  # LiteLLM catalogs are optional and best effort.
            return []


async def _resolve(lookup: Lookup, model: str) -> Any:
    value = lookup(model)
    return await value if inspect.isawaitable(value) else value


def _default_supported_params(model: str) -> list[str] | None:
    litellm = import_module("litellm")

    provider, _, bare_model = model.partition("/")
    return cast(
        list[str] | None,
        litellm.get_supported_openai_params(
            bare_model if provider else model,
            custom_llm_provider=provider or None,
        ),
    )


def _default_model_info(model: str) -> Mapping[str, Any]:
    litellm = import_module("litellm")

    return cast(Mapping[str, Any], litellm.get_model_info(model))


def _efforts(info: Mapping[str, Any]) -> list[str]:
    values = list(SUPPORTED_BASE)
    if info.get("supports_low_reasoning_effort") is False:
        values.remove("low")
    prefix = [value for value in ("none", "minimal") if info.get(_EXPLICIT_FLAGS[value]) is True]
    suffix = [value for value in ("xhigh", "max") if info.get(_EXPLICIT_FLAGS[value]) is True]
    values = prefix + values + suffix
    return list(dict.fromkeys(values))
