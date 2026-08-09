from __future__ import annotations

from typing import Final
from uuid import UUID

from codepilot.analyzers.risk_score import (
    QualityGateConfig,
    QualityGateFailure,
    QualityGateObserved,
    QualityGateResult,
    QualityGateThresholds,
    RiskAssessment,
)
from codepilot.domain.analysis import AnalysisSummary, AnalyzerOutcome
from codepilot.domain.insights import FileInsight
from codepilot.domain.quality import QualityGatePolicy, QualityProfile, QualityRule
from codepilot.repositories.analysis import _summary_from_json, _summary_to_json

FULL_SUMMARY: Final[AnalysisSummary] = AnalysisSummary(
    analyzed_file_count=3,
    source_lines=42,
    finding_count_by_severity={"critical": 1, "medium": 2},
    duration_seconds=1.25,
    analyzer_outcomes=(
        AnalyzerOutcome(
            analyzer="python",
            tool="ruff",
            version="1.0",
            status="succeeded",
            duration_seconds=0.5,
            language="python",
        ),
    ),
    risk_assessment=RiskAssessment(
        score=0.72,
        category="high",
        version="v1",
        components={"findings": 0.8},
        weights={"findings": 1.0},
    ),
    quality_gate=QualityGateResult(
        passed=False,
        failures=(QualityGateFailure("risk_score", "score too high"),),
        configured=True,
        thresholds=QualityGateThresholds(max_risk_score=0.6),
        observed=QualityGateObserved(new_critical_findings=1, risk_score=0.72, new_hotspots=2),
    ),
    baseline_analysis_id=UUID("11111111-1111-1111-1111-111111111111"),
    file_insights=(
        FileInsight(
            path="src/main.py",
            hotspot_score=0.9,
            risk=RiskAssessment(
                score=0.8,
                category="high",
                version="v1",
                components={"complexity": 0.8},
                weights={"complexity": 1.0},
            ),
            metrics={"complexity": 12.0},
        ),
    ),
    quality_policy=QualityGatePolicy(
        version=2,
        thresholds=QualityGateConfig(max_risk_score=0.6),
        profiles=(QualityProfile("python", (QualityRule("python", "ruff", "E501"),)),),
    ),
)


def test_summary_serialization_round_trip_preserves_all_optional_sections() -> None:
    encoded = _summary_to_json(FULL_SUMMARY)

    assert _summary_from_json(encoded) == FULL_SUMMARY


def test_summary_deserialization_keeps_legacy_payload_defaults() -> None:
    summary = _summary_from_json(
        {
            "analyzed_file_count": 1,
            "source_lines": 2,
            "finding_count_by_severity": {},
            "duration_seconds": 0.1,
            "analyzer_outcomes": [{"analyzer": "legacy"}],
        }
    )

    assert summary is not None
    assert summary.analyzer_outcomes[0].tool == "legacy"
    assert summary.analyzer_outcomes[0].status == "succeeded"
    assert summary.quality_gate is None
    assert summary.file_insights == ()


def test_summary_serialization_omits_empty_optional_collections() -> None:
    summary = AnalysisSummary(0, 0, {}, 0.0)

    assert set(_summary_to_json(summary)) == {
        "analyzed_file_count",
        "source_lines",
        "finding_count_by_severity",
        "duration_seconds",
        "analyzer_outcomes",
    }
