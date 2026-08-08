from __future__ import annotations

from codepilot.domain.analysis import AnalysisFinding
from codepilot.domain.insights import (
    FileInsight,
    build_file_insights,
    calculate_repository_risk,
    select_hotspots,
)


def _finding(path: str, severity: str = "warning") -> AnalysisFinding:
    return AnalysisFinding(path, "R1", severity, "message", 1, 1)


def test_build_file_insights_calculates_explainable_risk_from_available_evidence() -> None:
    insights = build_file_insights(
        findings=(_finding("src/a.py", "critical"), _finding("src/a.py", "warning")),
        history={"src/a.py": {"recent_churn": 50, "ownership_concentration": 0.75}},
        complexity={"src/a.py": 10},
        coupling={"src/a.py": (2, 3)},
    )

    insight = insights[0]
    assert insight.path == "src/a.py"
    assert insight.hotspot_score > 0
    assert insight.risk is not None
    assert set(insight.risk.components) == {
        "complexity",
        "recent_churn",
        "finding_severity",
        "coupling",
        "ownership_concentration",
    }
    assert insight.risk.reconstruct() == insight.risk.score


def test_select_hotspots_is_bounded_and_sorted() -> None:
    insights = (
        FileInsight("b.py", 0.8, None, {}),
        FileInsight("a.py", 0.8, None, {}),
        FileInsight("c.py", 0.2, None, {}),
    )

    assert [item.path for item in select_hotspots(insights, limit=2, minimum_score=0.5)] == [
        "a.py",
        "b.py",
    ]


def test_repository_risk_uses_maximum_real_component_and_omits_missing_data() -> None:
    insights = (
        FileInsight("a.py", 0.4, None, {"complexity": 0.8}),
        FileInsight("b.py", 0.2, None, {"recent_churn": 0.6}),
    )

    risk = calculate_repository_risk(insights)

    assert risk is not None
    assert risk.components == {"complexity": 0.8, "recent_churn": 0.6}
    assert risk.reconstruct() == risk.score
