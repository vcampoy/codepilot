from __future__ import annotations

from typing import Final

from codepilot.analyzers.risk_score import (
    FindingRisk,
    QualityGateConfig,
    RiskScoreConfig,
    calculate_risk,
    evaluate_quality_gates,
)

_EXPECTED_QUALITY_GATE_PROJECTION: Final[dict[str, object]] = {
    "passed": False,
    "failure_codes": frozenset({"critical-findings", "risk-score", "hotspots"}),
    "failure_details": (),
    "thresholds": (0, 0.7, 3),
    "observed": (1, 0.8, 4),
}


def test_risk_score_is_reconstructable_and_weight_changes_are_predictable() -> None:
    components = {
        "complexity": 0.8,
        "recent_churn": 0.4,
        "finding_severity": 1.0,
        "coupling": 0.2,
        "ownership_concentration": 0.6,
    }
    config = RiskScoreConfig(version="1.0", weights={key: 0.2 for key in components})
    score = calculate_risk(components, config)
    assert score.score == 0.6
    assert score.reconstruct() == score.score
    assert score.category == "medium"

    heavier = RiskScoreConfig(version="1.0", weights={**config.weights, "complexity": 0.6})
    assert calculate_risk(components, heavier).score > score.score


def test_quality_gates_prioritize_new_findings_and_explain_failures() -> None:
    findings = (
        FindingRisk("new-critical", "critical", is_new=True),
        FindingRisk("legacy-critical", "critical", is_new=False),
        FindingRisk("new-medium", "medium", is_new=True),
    )
    result = evaluate_quality_gates(
        findings,
        risk_score=0.8,
        hotspot_count=4,
        config=QualityGateConfig(
            max_new_critical_findings=0,
            max_risk_score=0.7,
            max_new_hotspots=3,
        ),
        new_hotspot_count=4,
    )
    projection = {
        "passed": result.passed,
        "failure_codes": frozenset(failure.code for failure in result.failures),
        "failure_details": tuple(
            failure.detail for failure in result.failures if failure.detail == "legacy-critical"
        ),
        "thresholds": (
            result.thresholds.max_new_critical_findings,
            result.thresholds.max_risk_score,
            result.thresholds.max_new_hotspots,
        ),
        "observed": (
            result.observed.new_critical_findings,
            result.observed.risk_score,
            result.observed.new_hotspots,
        ),
    }
    assert projection == _EXPECTED_QUALITY_GATE_PROJECTION


def test_empty_components_have_zero_risk_without_fake_precision() -> None:
    score = calculate_risk({}, RiskScoreConfig())
    assert score.score == 0.0
    assert score.components == {}
