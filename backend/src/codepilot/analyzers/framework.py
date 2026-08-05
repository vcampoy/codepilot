"""Deterministic contracts and orchestration for repository analyzers."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AnalyzerMetadata:
    """Stable identity and declared support for one analyzer."""

    name: str
    version: str
    supported_languages: frozenset[str]
    capabilities: frozenset[str] = frozenset()
    requirements: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalyzerContext:
    """Read-only context for an analyzer; repository code is never executed."""

    repository_path: Path
    commit_sha: str


@dataclass(frozen=True, slots=True)
class NormalizedFinding:
    """Language-neutral finding with a stable fingerprint."""

    analyzer: str
    rule_id: str
    severity: str
    category: str
    title: str
    description: str
    path: str
    start_line: int
    end_line: int
    evidence: str | None = None
    remediation: str | None = None

    @property
    def fingerprint(self) -> str:
        values = {
            "analyzer": self.analyzer,
            "rule_id": self.rule_id,
            "severity": self.severity,
            "category": self.category,
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "evidence": self.evidence,
        }
        canonical = json.dumps(values, sort_keys=True, separators=(",", ":"))
        return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AnalyzerMetrics:
    """Deterministic metrics emitted by an analyzer."""

    files_analyzed: int = 0
    source_lines: int = 0
    excluded_files: int = 0
    cyclomatic_complexity: int = 0
    maintainability_index: float | None = None


@dataclass(frozen=True, slots=True)
class AnalyzerExecution:
    """Tool execution metadata and availability state."""

    tool: str
    version: str | None
    duration_seconds: float
    available: bool
    message: str | None = None


@dataclass(frozen=True, slots=True)
class AnalyzerResult:
    """Analyzer output that can be combined without depending on ordering."""

    findings: tuple[NormalizedFinding, ...] = ()
    metrics: AnalyzerMetrics = field(default_factory=AnalyzerMetrics)
    execution: AnalyzerExecution | None = None


@dataclass(frozen=True, slots=True)
class AnalyzerFailure:
    """A partial failure that does not invalidate other analyzer results."""

    analyzer: str
    error_type: str
    message: str


class AnalyzerTimeoutError(TimeoutError):
    """An analyzer exceeded its execution budget."""


class Analyzer(Protocol):
    metadata: AnalyzerMetadata

    async def analyze(self, context: AnalyzerContext) -> AnalyzerResult: ...


class AnalyzerRegistry:
    """Explicit registry; no arbitrary dynamic plugin loading is supported."""

    def __init__(self) -> None:
        self._analyzers: dict[str, Analyzer] = {}

    def register(self, analyzer: Analyzer) -> None:
        name = analyzer.metadata.name
        if name in self._analyzers:
            raise ValueError(f"Analyzer {name!r} is already registered.")
        self._analyzers[name] = analyzer

    def __iter__(self) -> Iterator[Analyzer]:
        return iter(tuple(self._analyzers[name] for name in sorted(self._analyzers)))


@dataclass(frozen=True, slots=True)
class AnalyzerRun:
    """Combined output from all registered analyzers."""

    findings: tuple[NormalizedFinding, ...] = ()
    metrics: AnalyzerMetrics = field(default_factory=AnalyzerMetrics)
    failures: tuple[AnalyzerFailure, ...] = ()
    executions: tuple[AnalyzerExecution, ...] = ()


class DeterministicAnalyzerOrchestrator:
    """Run analyzers in stable order with isolated timeout/failure handling."""

    def __init__(self, registry: AnalyzerRegistry, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._registry = registry
        self._timeout_seconds = timeout_seconds

    async def run(self, context: AnalyzerContext) -> AnalyzerRun:
        findings: list[NormalizedFinding] = []
        failures: list[AnalyzerFailure] = []
        metrics = AnalyzerMetrics()
        executions: list[AnalyzerExecution] = []
        for analyzer in self._registry:
            try:
                result = await asyncio.wait_for(
                    analyzer.analyze(context), timeout=self._timeout_seconds
                )
            except TimeoutError as error:
                failures.append(
                    AnalyzerFailure(
                        analyzer.metadata.name,
                        AnalyzerTimeoutError.__name__,
                        "Analyzer execution exceeded its timeout.",
                    )
                )
                del error
                continue
            except Exception as error:  # noqa: BLE001 - partial failure is a contract
                failures.append(
                    AnalyzerFailure(
                        analyzer.metadata.name,
                        type(error).__name__,
                        str(error) or "Analyzer failed.",
                    )
                )
                continue
            findings.extend(result.findings)
            if result.execution is not None:
                executions.append(result.execution)
            metrics = AnalyzerMetrics(
                files_analyzed=metrics.files_analyzed + result.metrics.files_analyzed,
                source_lines=metrics.source_lines + result.metrics.source_lines,
                excluded_files=metrics.excluded_files + result.metrics.excluded_files,
                cyclomatic_complexity=metrics.cyclomatic_complexity
                + result.metrics.cyclomatic_complexity,
                maintainability_index=(
                    result.metrics.maintainability_index
                    if result.metrics.maintainability_index is not None
                    else metrics.maintainability_index
                ),
            )
        unique_findings = {finding.fingerprint: finding for finding in findings}
        return AnalyzerRun(
            findings=tuple(unique_findings[key] for key in sorted(unique_findings)),
            metrics=metrics,
            failures=tuple(sorted(failures, key=lambda failure: failure.analyzer)),
            executions=tuple(executions),
        )
