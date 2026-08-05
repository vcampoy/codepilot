"""Diff-focused pull-request comparison and quality-gate reporting."""

from __future__ import annotations

import re
from collections.abc import Iterable

from codepilot.analyzers.risk_score import (
    FindingRisk,
    QualityGateConfig,
    evaluate_quality_gates,
)
from codepilot.github.contracts import (
    FindingSnapshot,
    PullRequestComparison,
    QualityGateFailure,
    QualityGateSummary,
)

_HUNK_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def parse_added_lines(diff: str) -> dict[str, tuple[tuple[int, int], ...]]:
    """Return bounded added line ranges by file, excluding diff metadata."""
    ranges: dict[str, list[tuple[int, int]]] = {}
    current_file: str | None = None
    current_line = 0
    active_start: int | None = None
    active_end: int | None = None

    def flush() -> None:
        nonlocal active_start, active_end
        if current_file is not None and active_start is not None and active_end is not None:
            ranges.setdefault(current_file, []).append((active_start, active_end))
        active_start = None
        active_end = None

    for line in diff.splitlines():
        if line.startswith("diff --git "):
            flush()
            parts = line.split()
            current_file = parts[3][2:] if len(parts) >= 4 and parts[3].startswith("b/") else None
            continue
        if line.startswith("+++ b/"):
            flush()
            current_file = line[6:]
            continue
        hunk = _HUNK_PATTERN.match(line)
        if hunk:
            flush()
            current_line = int(hunk.group(1))
            continue
        if current_file is None or line.startswith("--- ") or line.startswith("diff "):
            continue
        if line.startswith("+") and not line.startswith("+++"):
            active_start = current_line if active_start is None else active_start
            active_end = current_line
            current_line += 1
        elif line.startswith("-"):
            continue
        else:
            flush()
            current_line += 1
    flush()
    return {path: tuple(values) for path, values in ranges.items()}


def compare_pull_request(
    baseline: Iterable[FindingSnapshot],
    current: Iterable[FindingSnapshot],
    *,
    baseline_hotspots: Iterable[str],
    current_hotspots: Iterable[str],
    baseline_risk: float,
    current_risk: float,
    max_new_critical_findings: int | None = None,
    max_risk_score: float | None = None,
    max_new_hotspots: int | None = None,
) -> PullRequestComparison:
    """Compare deterministic results and evaluate only new PR risk."""
    baseline_by_id = {finding.finding_id: finding for finding in baseline}
    current_by_id = {finding.finding_id: finding for finding in current}
    baseline_hotspot_paths = tuple(baseline_hotspots)
    current_hotspot_paths = tuple(current_hotspots)
    new_findings = tuple(
        current_by_id[finding_id]
        for finding_id in sorted(current_by_id.keys() - baseline_by_id.keys())
    )
    resolved_findings = tuple(
        baseline_by_id[finding_id]
        for finding_id in sorted(baseline_by_id.keys() - current_by_id.keys())
    )
    new_hotspots = tuple(sorted(set(current_hotspot_paths) - set(baseline_hotspot_paths)))
    gate = evaluate_quality_gates(
        tuple(
            FindingRisk(finding.finding_id, finding.severity, True)
            for finding in new_findings
        ),
        risk_score=current_risk,
        hotspot_count=len(current_hotspot_paths),
        new_hotspot_count=len(new_hotspots),
        config=QualityGateConfig(
            max_new_critical_findings=max_new_critical_findings,
            max_risk_score=max_risk_score,
            max_new_hotspots=max_new_hotspots,
        ),
    )
    return PullRequestComparison(
        new_findings=new_findings,
        resolved_findings=resolved_findings,
        risk_delta=round(current_risk - baseline_risk, 4),
        new_hotspots=new_hotspots,
        quality_gate=QualityGateSummary(
            passed=gate.passed,
            failures=tuple(
                QualityGateFailure(code=failure.code, detail=failure.detail)
                for failure in gate.failures
            ),
        ),
    )


def build_check_run_payload(
    comparison: PullRequestComparison,
    *,
    head_sha: str,
    details_url: str,
) -> dict[str, object]:
    """Build concise GitHub Check output without inline-comment noise."""
    new_count = len(comparison.new_findings)
    resolved_count = len(comparison.resolved_findings)
    conclusion = "success" if comparison.quality_gate.passed else "failure"
    summary = (
        f"{new_count} new finding(s), {resolved_count} resolved, "
        f"risk delta {comparison.risk_delta:+.4f}, "
        f"{len(comparison.new_hotspots)} new hotspot(s)."
    )
    return {
        "name": "CodePilot",
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": conclusion,
        "details_url": details_url,
        "output": {
            "title": f"CodePilot quality gate: {conclusion}",
            "summary": summary,
            "text": "See the CodePilot analysis for evidence and remediation details.",
        },
    }
