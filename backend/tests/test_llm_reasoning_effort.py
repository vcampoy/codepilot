from __future__ import annotations

import asyncio

from codepilot.llm.reasoning_effort import ReasoningEffortResolver
from codepilot.services.llm_configuration import _capability_model


def test_reasoning_efforts_use_supported_parameters_and_model_flags() -> None:
    resolver = ReasoningEffortResolver(
        supported_params=lambda model: ["reasoning_effort"],
        model_info=lambda model: {
            "supports_none_reasoning_effort": True,
            "supports_minimal_reasoning_effort": True,
            "supports_xhigh_reasoning_effort": True,
            "supports_max_reasoning_effort": True,
        },
    )

    assert asyncio.run(resolver.for_model("openai/gpt-5")) == [
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ]


def test_resolver_fails_closed_when_model_does_not_support_effort() -> None:
    resolver = ReasoningEffortResolver(supported_params=lambda _: ["temperature"])
    assert asyncio.run(resolver.for_model("openai/gpt-4o")) == []


def test_resolver_fails_closed_when_litellm_lookup_raises() -> None:
    def unsupported(_: str) -> list[str]:
        raise RuntimeError("unknown model")

    resolver = ReasoningEffortResolver(supported_params=unsupported)
    assert asyncio.run(resolver.for_model("unknown/model")) == []


def test_capability_model_uses_litellm_provider_route() -> None:
    resolver = ReasoningEffortResolver(
        supported_params=lambda model: (
            ["reasoning_effort"] if model == "gemini/gemini-2.5-pro" else []
        ),
        model_info=lambda _: {"supports_minimal_reasoning_effort": True},
    )

    routed = _capability_model("google", "gemini-2.5-pro")
    assert routed == "gemini/gemini-2.5-pro"
    assert asyncio.run(resolver.for_model(routed)) == ["minimal", "low", "medium", "high"]
