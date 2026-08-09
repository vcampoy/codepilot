"""Transparent, versioned risk scoring and quality-gate contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

DEFAULT_WEIGHTS = {
    "complexity": 0.25,
    "recent_churn": 0.2,
    "finding_severity": 0.3,
    "coupling": 0.15,
    "ownership_concentration": 0.1,
}


@dataclass(frozen=True, slots=True)
class RiskScoreConfig:
    version: str = "1.0"
    weights: Mapping[str, float] = field(default_factory=lambda: DEFAULT_WEIGHTS.copy())

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("version is required")
        if not self.weights or any(value < 0 for value in self.weights.values()):
            raise ValueError("weights must contain non-negative values")
        if sum(self.weights.values()) <= 0:
            raise ValueError("at least one weight must be positive")


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    score: float
    category: str
    version: str
    components: dict[str, float]
    weights: dict[str, float]

    def reconstruct(self) -> float:
        total = sum(self.weights.get(name, 0.0) * value for name, value in self.components.items())
        denominator = sum(self.weights.get(name, 0.0) for name in self.components)
        return round(total / denominator, 4) if denominator else 0.0


@dataclass(frozen=True, slots=True)
class FindingRisk:
    finding_id: str
    severity: str
    is_new: bool
    analyzer: str | None = None
    rule_id: str | None = None


@dataclass(frozen=True, slots=True)
class QualityGateConfig:
    max_new_critical_findings: int | None = None
    max_risk_score: float | None = None
    max_new_hotspots: int | None = None

    def __post_init__(self) -> None:
        if self.max_new_critical_findings is not None and self.max_new_critical_findings < 0:
            raise ValueError("max_new_critical_findings cannot be negative")
        if self.max_risk_score is not None and not 0 <= self.max_risk_score <= 1:
            raise ValueError("max_risk_score must be between zero and one")
        if self.max_new_hotspots is not None and self.max_new_hotspots < 0:
            raise ValueError("max_new_hotspots cannot be negative")


@dataclass(frozen=True, slots=True)
class QualityGateFailure:
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class QualityGateThresholds:
    """Thresholds captured with a gate so its configuration is auditable."""

    max_new_critical_findings: int | None = None
    max_risk_score: float | None = None
    max_new_hotspots: int | None = None


@dataclass(frozen=True, slots=True)
class QualityGateObserved:
    """Evidence evaluated by a quality gate."""

    new_critical_findings: int
    risk_score: float | None
    new_hotspots: int


@dataclass(frozen=True, slots=True)
class QualityGateResult:
    passed: bool
    failures: tuple[QualityGateFailure, ...]
    configured: bool = True
    thresholds: QualityGateThresholds = field(default_factory=QualityGateThresholds)
    observed: QualityGateObserved = field(default_factory=lambda: QualityGateObserved(0, None, 0))

    @property
    def status(self) -> str:
        if not self.configured:
            return "not_configured"
        return "passed" if self.passed else "failed"


def calculate_risk(components: Mapping[str, float], config: RiskScoreConfig) -> RiskAssessment:
    normalized = {
        name: round(min(max(float(value), 0.0), 1.0), 4)
        for name, value in components.items()
        if name in config.weights
    }
    weights = {name: float(config.weights[name]) for name in normalized}
    denominator = sum(weights.values())
    score = (
        round(sum(weights[name] * value for name, value in normalized.items()) / denominator, 4)
        if denominator
        else 0.0
    )
    return RiskAssessment(score, _category(score), config.version, normalized, weights)


def evaluate_quality_gates(
    findings: tuple[FindingRisk, ...],
    *,
    risk_score: float,
    hotspot_count: int,
    config: QualityGateConfig,
    new_hotspot_count: int | None = None,
    enabled_rules: tuple[object, ...] = (),
) -> QualityGateResult:
    critical = _new_critical_findings(findings)
    enabled_rule_keys = _enabled_rule_keys(enabled_rules)
    matched_rules = _matching_enabled_rules(findings, enabled_rule_keys)
    failures = [
        failure
        for failure in (
            _critical_failure(critical, config),
            _enabled_rules_failure(matched_rules, enabled_rule_keys),
            _risk_failure(risk_score, config),
            _hotspot_failure(new_hotspot_count, config),
        )
        if failure is not None
    ]
    observed_hotspots = hotspot_count if new_hotspot_count is None else new_hotspot_count
    configured = any(
        value is not None
        for value in (
            config.max_new_critical_findings,
            config.max_risk_score,
            config.max_new_hotspots,
        )
    )
    return QualityGateResult(
        passed=not failures,
        failures=tuple(failures),
        configured=configured,
        thresholds=QualityGateThresholds(
            max_new_critical_findings=config.max_new_critical_findings,
            max_risk_score=config.max_risk_score,
            max_new_hotspots=config.max_new_hotspots,
        ),
        observed=QualityGateObserved(
            new_critical_findings=len(critical),
            risk_score=risk_score,
            new_hotspots=observed_hotspots,
        ),
    )


def _new_critical_findings(findings: tuple[FindingRisk, ...]) -> tuple[str, ...]:
    return tuple(
        finding.finding_id
        for finding in findings
        if finding.is_new and finding.severity.casefold() == "critical"
    )


def _enabled_rule_keys(enabled_rules: tuple[object, ...]) -> set[tuple[str, str]]:
    return {(getattr(rule, "analyzer", ""), getattr(rule, "rule_id", "")) for rule in enabled_rules}


def _matching_enabled_rules(
    findings: tuple[FindingRisk, ...], enabled_rule_keys: set[tuple[str, str]]
) -> tuple[str, ...]:
    return tuple(
        finding.finding_id
        for finding in findings
        if finding.is_new
        and finding.analyzer is not None
        and finding.rule_id is not None
        and any(
            finding.rule_id == rule_id
            and (finding.analyzer == analyzer or finding.analyzer.endswith(f".{analyzer}"))
            for analyzer, rule_id in enabled_rule_keys
        )
    )


def _critical_failure(
    critical: tuple[str, ...], config: QualityGateConfig
) -> QualityGateFailure | None:
    limit = config.max_new_critical_findings
    if limit is None or len(critical) <= limit:
        return None
    return QualityGateFailure(
        "critical-findings",
        f"{len(critical)} new critical findings exceed the limit of {limit}.",
    )


def _enabled_rules_failure(
    matched_rules: tuple[str, ...], enabled_rule_keys: set[tuple[str, str]]
) -> QualityGateFailure | None:
    if not enabled_rule_keys or not matched_rules:
        return None
    return QualityGateFailure(
        "enabled-rules",
        f"{len(matched_rules)} findings match enabled quality-profile rules.",
    )


def _risk_failure(risk_score: float, config: QualityGateConfig) -> QualityGateFailure | None:
    limit = config.max_risk_score
    if limit is None or risk_score <= limit:
        return None
    return QualityGateFailure("risk-score", f"Risk score {risk_score:.4f} exceeds {limit:.4f}.")


def _hotspot_failure(
    new_hotspot_count: int | None, config: QualityGateConfig
) -> QualityGateFailure | None:
    limit = config.max_new_hotspots
    if new_hotspot_count is None or limit is None or new_hotspot_count <= limit:
        return None
    return QualityGateFailure(
        "hotspots",
        f"{new_hotspot_count} new hotspots exceed the limit of {limit}.",
    )


def _category(score: float) -> str:
    if score < 0.33:
        return "low"
    if score < 0.66:
        return "medium"
    if score < 0.85:
        return "high"
    return "critical"
