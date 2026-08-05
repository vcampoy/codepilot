from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from codepilot.analyzers.framework import (
    AnalyzerContext,
    AnalyzerFailure,
    AnalyzerMetadata,
    AnalyzerRegistry,
    AnalyzerResult,
    AnalyzerTimeoutError,
    DeterministicAnalyzerOrchestrator,
    NormalizedFinding,
)
from codepilot.analyzers.generic import (
    BasicFileMetricsAnalyzer,
    LargeSourceFileAnalyzer,
    LongLineAnalyzer,
)


def metadata(name: str) -> AnalyzerMetadata:
    return AnalyzerMetadata(name=name, version="1.0.0", supported_languages=frozenset())


class StubAnalyzer:
    def __init__(
        self,
        name: str,
        result: AnalyzerResult | None = None,
        error: Exception | None = None,
    ):
        self.metadata = metadata(name)
        self.result = result or AnalyzerResult()
        self.error = error

    async def analyze(self, context: AnalyzerContext) -> AnalyzerResult:
        del context
        if self.error:
            raise self.error
        return self.result


def test_registry_orders_analyzers_and_rejects_duplicate_names() -> None:
    registry = AnalyzerRegistry()
    registry.register(StubAnalyzer("zeta"))
    registry.register(StubAnalyzer("alpha"))

    assert [analyzer.metadata.name for analyzer in registry] == ["alpha", "zeta"]
    with pytest.raises(ValueError, match="already registered"):
        registry.register(StubAnalyzer("alpha"))


def test_orchestrator_preserves_findings_when_one_analyzer_fails(tmp_path: Path) -> None:
    finding = NormalizedFinding(
        analyzer="alpha",
        rule_id="A001",
        severity="warning",
        category="quality",
        title="Example",
        description="Example finding",
        path="src/a.py",
        start_line=1,
        end_line=1,
    )
    registry = AnalyzerRegistry()
    registry.register(StubAnalyzer("alpha", AnalyzerResult(findings=(finding,))))
    registry.register(StubAnalyzer("broken", error=RuntimeError("boom")))

    result = asyncio.run(
        DeterministicAnalyzerOrchestrator(registry, timeout_seconds=1).run(
            AnalyzerContext(tmp_path, "abc123")
        )
    )

    assert result.findings == (finding,)
    assert result.failures == (AnalyzerFailure("broken", "RuntimeError", "boom"),)


def test_orchestrator_records_timeout_without_invalidating_other_results(tmp_path: Path) -> None:
    class SlowAnalyzer(StubAnalyzer):
        async def analyze(self, context: AnalyzerContext) -> AnalyzerResult:
            del context
            await asyncio.sleep(0.05)
            return AnalyzerResult()

    registry = AnalyzerRegistry()
    registry.register(SlowAnalyzer("slow"))

    result = asyncio.run(
        DeterministicAnalyzerOrchestrator(registry, timeout_seconds=0.001).run(
            AnalyzerContext(tmp_path, "abc123")
        )
    )

    assert result.findings == ()
    assert result.failures[0].error_type == AnalyzerTimeoutError.__name__


def test_generic_analyzers_are_deterministic_and_ignore_untrusted_directories(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "vendor").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / "src" / "large.py").write_text("x = 1\n" * 3, encoding="utf-8")
    (tmp_path / "src" / "long.py").write_text("x = '" + ("a" * 20) + "'\n", encoding="utf-8")
    (tmp_path / "vendor" / "ignored.py").write_text("x = 1\n" * 100, encoding="utf-8")
    context = AnalyzerContext(tmp_path, "abc123")

    async def run() -> tuple[AnalyzerResult, AnalyzerResult, AnalyzerResult]:
        return (
            await LargeSourceFileAnalyzer(max_source_bytes=10).analyze(context),
            await LongLineAnalyzer(max_line_length=10).analyze(context),
            await BasicFileMetricsAnalyzer().analyze(context),
        )

    first = asyncio.run(run())
    second = asyncio.run(run())
    assert first == second
    assert {finding.path for finding in first[0].findings} == {"src/large.py", "src/long.py"}
    assert {finding.path for finding in first[1].findings} == {"src/long.py"}
    assert first[2].metrics.files_analyzed == 2
