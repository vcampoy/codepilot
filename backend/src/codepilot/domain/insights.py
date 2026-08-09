"""Explainable, persisted insights derived from deterministic analysis evidence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from codepilot.analyzers.risk_score import RiskAssessment, RiskScoreConfig, calculate_risk
from codepilot.domain.analysis import AnalysisFinding

_SEVERITY_WEIGHTS = {
    "critical": 4.0,
    "error": 3.0,
    "high": 3.0,
    "warning": 2.0,
    "medium": 2.0,
    "info": 1.0,
    "low": 1.0,
}


@dataclass(frozen=True, slots=True)
class FileInsight:
    path: str
    hotspot_score: float
    risk: RiskAssessment | None
    metrics: dict[str, float]


def build_file_insights(
    *,
    findings: Sequence[AnalysisFinding],
    history: Mapping[str, Mapping[str, float]],
    complexity: Mapping[str, float],
    coupling: Mapping[str, tuple[int, int]],
    risk_config: RiskScoreConfig | None = None,
) -> tuple[FileInsight, ...]:
    """Build file-level insights without fabricating unavailable components."""
    paths = _insight_paths(findings, history, complexity, coupling)
    findings_by_path = _findings_by_path(findings)
    config = risk_config or RiskScoreConfig()
    return tuple(
        _file_insight(
            path,
            findings_by_path.get(path, ()),
            history.get(path, {}),
            complexity,
            coupling,
            config,
        )
        for path in sorted(paths)
    )


def _insight_paths(
    findings: Sequence[AnalysisFinding],
    history: Mapping[str, Mapping[str, float]],
    complexity: Mapping[str, float],
    coupling: Mapping[str, tuple[int, int]],
) -> set[str]:
    return set(history) | set(complexity) | set(coupling) | {finding.path for finding in findings}


def _findings_by_path(
    findings: Sequence[AnalysisFinding],
) -> dict[str, tuple[AnalysisFinding, ...]]:
    grouped: dict[str, list[AnalysisFinding]] = defaultdict(list)
    for finding in findings:
        grouped[finding.path].append(finding)
    return {path: tuple(values) for path, values in grouped.items()}


def _file_insight(
    path: str,
    path_findings: Sequence[AnalysisFinding],
    history_values: Mapping[str, float],
    complexity: Mapping[str, float],
    coupling: Mapping[str, tuple[int, int]],
    config: RiskScoreConfig,
) -> FileInsight:
    metrics = _insight_metrics(path, path_findings, history_values, complexity, coupling)
    return FileInsight(
        path,
        _hotspot_score(path, path_findings, history_values, complexity),
        calculate_risk(metrics, config) if metrics else None,
        metrics,
    )


def _insight_metrics(
    path: str,
    findings: Sequence[AnalysisFinding],
    history_values: Mapping[str, float],
    complexity: Mapping[str, float],
    coupling: Mapping[str, tuple[int, int]],
) -> dict[str, float]:
    metrics: dict[str, float] = {}
    if path in complexity:
        metrics["complexity"] = _normalize(complexity[path], 20.0)
    if "recent_churn" in history_values:
        metrics["recent_churn"] = _normalize(history_values["recent_churn"], 100.0)
    if findings:
        severity_total = sum(
            _SEVERITY_WEIGHTS.get(finding.severity.casefold(), 1.0) for finding in findings
        )
        metrics["finding_severity"] = _normalize(severity_total, 10.0)
    if path in coupling:
        incoming, outgoing = coupling[path]
        metrics["coupling"] = _normalize(incoming + outgoing, 25.0)
    if "ownership_concentration" in history_values:
        metrics["ownership_concentration"] = _normalize(
            history_values["ownership_concentration"], 1.0
        )
    return metrics


def _hotspot_score(
    path: str,
    findings: Sequence[AnalysisFinding],
    history_values: Mapping[str, float],
    complexity: Mapping[str, float],
) -> float:
    raw_complexity = float(complexity.get(path, 0.0))
    raw_churn = float(history_values.get("recent_churn", 0.0))
    return round(
        _normalize(raw_complexity, 20.0) * 0.5
        + _normalize(raw_churn, 100.0) * 0.3
        + _normalize(float(len(findings)), 10.0) * 0.2,
        4,
    )


def calculate_repository_risk(
    insights: Sequence[FileInsight], risk_config: RiskScoreConfig | None = None
) -> RiskAssessment | None:
    """Use the highest real component as a conservative repository assessment."""
    components: dict[str, float] = {}
    for insight in insights:
        for name, value in insight.metrics.items():
            components[name] = max(components.get(name, 0.0), value)
    return calculate_risk(components, risk_config or RiskScoreConfig()) if components else None


def select_hotspots(
    insights: Sequence[FileInsight], *, limit: int = 20, minimum_score: float = 0.5
) -> tuple[FileInsight, ...]:
    if limit <= 0:
        return ()
    return tuple(
        sorted(
            (insight for insight in insights if insight.hotspot_score >= minimum_score),
            key=lambda insight: (-insight.hotspot_score, insight.path),
        )[: min(limit, 100)]
    )


def _normalize(value: float, denominator: float) -> float:
    return round(min(max(float(value) / denominator, 0.0), 1.0), 4)
