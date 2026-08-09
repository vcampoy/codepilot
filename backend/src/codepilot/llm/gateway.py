"""LiteLLM adapter behind the application-owned LLM gateway."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from pydantic import BaseModel

from codepilot.llm.contracts import (
    DeterministicEvidence,
    DeterministicSummaryOutput,
    EnrichmentResult,
    EnrichmentTask,
    ExplanationOutput,
    LlmInvalidResponseError,
    LlmProviderError,
    LlmRequest,
    LlmUsage,
    ProviderCompletion,
    RefactoringPlanOutput,
)
from codepilot.llm.prompts import build_prompt

LOGGER = logging.getLogger(__name__)
Completion = Callable[..., Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class LlmMetricsEvent:
    """One provider attempt, including cost and latency when known."""

    task: EnrichmentTask
    model: str
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    cache_hit: bool = False


class InMemoryLlmMetricsSink:
    """Small bounded-test-friendly metrics sink; production can replace it."""

    def __init__(self, max_events: int = 1_000) -> None:
        self._max_events = max_events
        self.events: list[LlmMetricsEvent] = []

    def record(self, event: LlmMetricsEvent) -> None:
        self.events.append(event)
        if len(self.events) > self._max_events:
            del self.events[: len(self.events) - self._max_events]


class LiteLlmGateway:
    """Application gateway with retries, fallbacks, validation, and caching."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None,
        provider: str = "litellm",
        fallback_models: Sequence[str] = (),
        models_by_task: Mapping[EnrichmentTask, Sequence[str]] | None = None,
        timeout_seconds: float = 30,
        max_tokens: int = 1_200,
        max_retries: int = 2,
        cache_size: int = 256,
        completion: Completion | None = None,
        metrics_sink: InMemoryLlmMetricsSink | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._provider = provider
        self._models = tuple(dict.fromkeys((model, *fallback_models)))
        self._models_by_task = models_by_task or {}
        self._timeout_seconds = timeout_seconds
        self._max_tokens = max_tokens
        self._max_retries = max_retries
        self._cache_size = cache_size
        self._completion = completion or self._load_completion()
        self._cache: dict[str, EnrichmentResult] = {}
        self._metrics = metrics_sink or InMemoryLlmMetricsSink()

    async def enrich(
        self, task: EnrichmentTask, evidence: DeterministicEvidence
    ) -> EnrichmentResult:
        last_error: Exception | None = None
        models = tuple(dict.fromkeys((*self._models_by_task.get(task, ()), *self._models)))
        for model in models:
            request = build_prompt(
                task,
                evidence,
                model=model,
                max_tokens=self._max_tokens,
            )
            cached = self._cache.get(request.cache_key)
            if cached is not None:
                return cached.model_copy(update={"cache_hit": True})
            for attempt in range(self._max_retries + 1):
                started = time.perf_counter()
                try:
                    completion = await asyncio.wait_for(
                        self._call_provider(request), timeout=self._timeout_seconds
                    )
                    result = self._build_result(task, evidence, request, completion, started)
                    self._remember(request.cache_key, result)
                    return result
                except LlmInvalidResponseError:
                    raise
                # Optional provider SDKs expose incompatible exception classes;
                # normalize at the boundary.
                except Exception as error:  # noqa: BLE001
                    last_error = error
                    self._record_failure(task, model, started)
                    if not _is_retryable(error) or attempt == self._max_retries:
                        break
                    await asyncio.sleep(min(0.25 * (2**attempt), 1.0))
        raise LlmProviderError("All configured LLM models failed.") from last_error

    async def _call_provider(self, request: LlmRequest) -> ProviderCompletion:
        kwargs: dict[str, object] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "max_tokens": request.max_tokens,
            "timeout": self._timeout_seconds,
            "response_format": {"type": "json_object"},
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
        raw = await self._completion(**kwargs)
        return _normalize_completion(raw, request.model, self._provider)

    def _build_result(
        self,
        task: EnrichmentTask,
        evidence: DeterministicEvidence,
        request: LlmRequest,
        completion: ProviderCompletion,
        started: float,
    ) -> EnrichmentResult:
        output_model = _output_model(task)
        try:
            structured = output_model.model_validate_json(completion.content)
        except Exception as error:
            raise LlmInvalidResponseError("Provider returned invalid structured output.") from error
        data = structured.model_dump(mode="json")
        citations = _citations(data)
        unknown = set(citations) - evidence.citation_ids()
        if unknown:
            raise LlmInvalidResponseError("Provider cited evidence that is not stored.")
        latency_ms = (time.perf_counter() - started) * 1_000
        event = LlmMetricsEvent(
            task=task,
            model=completion.model,
            latency_ms=latency_ms,
            input_tokens=completion.usage.input_tokens,
            output_tokens=completion.usage.output_tokens,
            cost_usd=completion.usage.cost_usd,
        )
        self._metrics.record(event)
        LOGGER.info(
            "llm_completion",
            extra={
                "task": task.value,
                "model": completion.model,
                "latency_ms": latency_ms,
                "input_tokens": completion.usage.input_tokens,
                "output_tokens": completion.usage.output_tokens,
                "cost_usd": completion.usage.cost_usd,
                "cache_hit": False,
            },
        )
        return EnrichmentResult(
            task=task,
            analysis_id=evidence.analysis_id,
            enabled=True,
            ai_generated=True,
            text=_result_text(data),
            structured=data,
            citations=citations,
            model=completion.model,
            provider=completion.provider,
            usage=completion.usage,
            latency_ms=latency_ms,
        )

    def _remember(self, cache_key: str, result: EnrichmentResult) -> None:
        self._cache[cache_key] = result
        if len(self._cache) > self._cache_size:
            del self._cache[next(iter(self._cache))]

    def _record_failure(self, task: EnrichmentTask, model: str, started: float) -> None:
        self._metrics.record(
            LlmMetricsEvent(
                task=task,
                model=model,
                latency_ms=(time.perf_counter() - started) * 1_000,
                input_tokens=0,
                output_tokens=0,
                cost_usd=None,
            )
        )

    @staticmethod
    def _load_completion() -> Completion:
        try:
            import litellm  # type: ignore[import-not-found]
        except ImportError as error:
            raise LlmProviderError(
                "LiteLLM is not installed. Install the backend 'llm' extra to enable AI."
            ) from error
        return cast(Completion, litellm.acompletion)


def _output_model(task: EnrichmentTask) -> type[BaseModel]:
    return cast(
        type[BaseModel],
        {
            EnrichmentTask.FILE_RISK: ExplanationOutput,
            EnrichmentTask.REFACTORING_PLAN: RefactoringPlanOutput,
            EnrichmentTask.DETERMINISTIC_SUMMARY: DeterministicSummaryOutput,
        }[task],
    )


def _citations(data: dict[str, Any]) -> list[str]:
    citations = data.get("citations")
    if citations is not None:
        return [str(item) for item in citations]
    return [str(item) for plan in data.get("items", []) for item in plan.get("citations", [])]


def _result_text(data: dict[str, Any]) -> str:
    if "summary" in data:
        return str(data["summary"])
    return " ".join(str(item.get("action", "")) for item in data.get("items", []))


def _normalize_completion(raw: Any, model: str, provider: str) -> ProviderCompletion:
    if isinstance(raw, ProviderCompletion):
        return raw
    choices = _raw_field(raw, "choices")
    if not choices:
        raise LlmProviderError("Provider returned no choices.")
    first = choices[0]
    message = _raw_field(first, "message")
    content = _raw_field(message, "content")
    usage_raw = _raw_field(raw, "usage")
    usage = _normalize_usage(usage_raw)
    return ProviderCompletion(
        content=str(content),
        model=str(_raw_field(raw, "model") or model),
        provider=provider,
        usage=usage,
    )


def _raw_field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _normalize_usage(raw: Any) -> LlmUsage:
    if raw is None:
        return LlmUsage()
    getter = raw.get if isinstance(raw, dict) else lambda key, default=0: getattr(raw, key, default)
    return LlmUsage(
        input_tokens=int(getter("prompt_tokens", 0) or 0),
        output_tokens=int(getter("completion_tokens", 0) or 0),
        cost_usd=(float(getter("cost", 0)) if getter("cost", None) is not None else None),
    )


def _is_retryable(error: Exception) -> bool:
    if isinstance(error, (TimeoutError, asyncio.TimeoutError, ConnectionError)):
        return True
    status_code = getattr(error, "status_code", None)
    return isinstance(status_code, int) and (status_code == 429 or status_code >= 500)
