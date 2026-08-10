"""Production composition adapter for deterministic repository analysis."""

from __future__ import annotations

import asyncio
from pathlib import Path

from codepilot.analyzers.dependency_graph import DependencyGraphBuilder
from codepilot.analyzers.framework import (
    Analyzer,
    AnalyzerContext,
    AnalyzerRegistry,
    AnalyzerRun,
    DeterministicAnalyzerOrchestrator,
    NormalizedFinding,
)
from codepilot.analyzers.generic import (
    BasicFileMetricsAnalyzer,
    LargeSourceFileAnalyzer,
    LongLineAnalyzer,
)
from codepilot.analyzers.git_history import GitHistoryError, GitHistoryService
from codepilot.analyzers.multilanguage_adapters import EslintAnalyzer
from codepilot.analyzers.python_adapters import (
    BanditAnalyzer,
    RadonAnalyzer,
    RuffAnalyzer,
)
from codepilot.domain.analysis import AnalysisFinding, AnalysisResult, AnalyzerOutcome
from codepilot.domain.insights import build_file_insights
from codepilot.services.repository_ingestion import RepositorySnapshot

_LANGUAGE_MAP = {"Python": "python", "JavaScript": "javascript", "TypeScript": "typescript"}


class ProductionRepositoryAnalyzer:
    """Compose only fixed, dependency-injected analyzers; never loads target config."""

    def __init__(self, *, tool_timeout_seconds: float = 60.0) -> None:
        self._tool_timeout_seconds = tool_timeout_seconds
        self._history = GitHistoryService()
        self._graph = DependencyGraphBuilder()

    def _registry(self, languages: set[str]) -> AnalyzerRegistry:
        registry = AnalyzerRegistry()
        analyzers: list[Analyzer] = [
            BasicFileMetricsAnalyzer(),
            LargeSourceFileAnalyzer(),
            LongLineAnalyzer(),
        ]
        for analyzer in analyzers:
            registry.register(analyzer)
        if "python" in languages:
            language_analyzers: list[Analyzer] = [
                RuffAnalyzer(timeout_seconds=self._tool_timeout_seconds),
                BanditAnalyzer(timeout_seconds=self._tool_timeout_seconds),
                RadonAnalyzer(timeout_seconds=self._tool_timeout_seconds),
            ]
            for analyzer in language_analyzers:
                registry.register(analyzer)
        if languages & {"javascript", "typescript"}:
            analyzer = EslintAnalyzer(timeout_seconds=self._tool_timeout_seconds)
            registry.register(analyzer)
        return registry

    async def analyze(self, snapshot: RepositorySnapshot) -> AnalysisResult:
        languages = _supported_languages(snapshot)
        registry = self._registry(languages)
        run = await DeterministicAnalyzerOrchestrator(registry, self._tool_timeout_seconds).run(
            AnalyzerContext(snapshot.repository_path, snapshot.commit_sha)
        )
        outcomes = _build_outcomes(registry, run, languages)
        findings = _normalize_findings(run)
        graph_coupling, graph_findings, graph_outcome = await self._collect_graph(
            snapshot.repository_path
        )
        findings.extend(graph_findings)
        if graph_outcome is not None:
            outcomes.append(graph_outcome)
        history, history_outcome = await self._collect_history(snapshot.repository_path, findings)
        if history_outcome is not None:
            outcomes.append(history_outcome)
        file_insights = build_file_insights(
            findings=findings, history=history, complexity={}, coupling=graph_coupling
        )
        return AnalysisResult(
            run.metrics.files_analyzed,
            run.metrics.source_lines,
            tuple(findings),
            tuple(outcomes),
            True,
            file_insights,
        )

    async def _collect_graph(
        self, repository_path: Path
    ) -> tuple[dict[str, tuple[int, int]], list[AnalysisFinding], AnalyzerOutcome | None]:
        try:
            graph = await asyncio.to_thread(self._graph.build, repository_path)
        except (OSError, ValueError) as error:
            return (
                {},
                [],
                AnalyzerOutcome(
                    "dependency.graph",
                    "dependency.graph",
                    None,
                    "failed",
                    0.0,
                    str(error),
                    None,
                    True,
                ),
            )
        coupling = {
            node: (graph.in_degree.get(node, 0), graph.out_degree.get(node, 0))
            for node in set(graph.in_degree) | set(graph.out_degree)
        }
        return coupling, _normalize_graph_findings(graph.findings), None

    async def _collect_history(
        self, repository_path: Path, findings: list[AnalysisFinding]
    ) -> tuple[dict[str, dict[str, float]], AnalyzerOutcome | None]:
        try:
            metrics = await asyncio.to_thread(
                self._history.collect,
                repository_path,
                finding_density_by_path=_finding_density(findings),
            )
        except GitHistoryError as error:
            return {}, AnalyzerOutcome(
                "git.history", "git.history", None, "failed", 0.0, str(error), None, True
            )
        return {
            path: {
                "recent_churn": metric.recent_churn,
                "ownership_concentration": metric.ownership_concentration,
            }
            for path, metric in metrics.by_path.items()
        }, None


def _supported_languages(snapshot: RepositorySnapshot) -> set[str]:
    return {_LANGUAGE_MAP[value] for value in snapshot.primary_languages if value in _LANGUAGE_MAP}


def _build_outcomes(
    registry: AnalyzerRegistry, run: AnalyzerRun, languages: set[str]
) -> list[AnalyzerOutcome]:
    failed = {failure.analyzer: failure for failure in run.failures}
    executions = {execution.tool: execution for execution in run.executions}
    outcomes: list[AnalyzerOutcome] = []
    for analyzer in registry:
        metadata = analyzer.metadata
        execution = executions.get(metadata.name) or executions.get(
            metadata.name.rsplit(".", 1)[-1]
        )
        failure = failed.get(metadata.name)
        language = next(iter(metadata.supported_languages & languages), None)
        if failure is not None:
            outcomes.append(
                AnalyzerOutcome(
                    metadata.name,
                    metadata.name,
                    None,
                    "failed",
                    0.0,
                    failure.message,
                    language,
                    metadata.name.startswith("generic."),
                )
            )
        elif execution is None:
            outcomes.append(
                AnalyzerOutcome(
                    metadata.name,
                    metadata.name,
                    None,
                    "failed",
                    0.0,
                    "Analyzer produced no execution evidence.",
                    language,
                    metadata.name.startswith("generic."),
                )
            )
        else:
            outcomes.append(
                AnalyzerOutcome(
                    metadata.name,
                    execution.tool,
                    execution.version,
                    "succeeded" if execution.available else "skipped",
                    execution.duration_seconds,
                    execution.message,
                    language,
                    metadata.name.startswith("generic."),
                )
            )
    return outcomes


def _normalize_findings(run: AnalyzerRun) -> list[AnalysisFinding]:
    return [
        AnalysisFinding(
            path=Path(finding.path).as_posix(),
            rule_id=finding.rule_id,
            severity=finding.severity,
            message=finding.description,
            start_line=finding.start_line,
            end_line=finding.end_line,
            analyzer=finding.analyzer,
            category=finding.category,
            title=finding.title,
            evidence=finding.evidence,
            remediation=finding.remediation,
        )
        for finding in run.findings
    ]


def _normalize_graph_findings(
    findings: tuple[NormalizedFinding, ...],
) -> list[AnalysisFinding]:
    return [
        AnalysisFinding(
            path=finding.path,
            rule_id=finding.rule_id,
            severity=finding.severity,
            message=finding.description,
            start_line=finding.start_line,
            end_line=finding.end_line,
            analyzer=finding.analyzer,
            category=finding.category,
            title=finding.title,
            evidence=finding.evidence,
            remediation=finding.remediation,
        )
        for finding in findings
    ]


def _finding_density(findings: list[AnalysisFinding]) -> dict[str, float]:
    counts: dict[str, float] = {}
    for finding in findings:
        counts[finding.path] = counts.get(finding.path, 0.0) + 1.0
    return counts
