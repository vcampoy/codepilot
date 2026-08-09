# ruff: noqa: E501
"""Project quality-gate policies and defensive SonarQube profile imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from codepilot.analyzers.risk_score import QualityGateConfig

SUPPORTED_ANALYZERS: Final[frozenset[str]] = frozenset({"ruff", "bandit", "eslint", "radon"})
SONAR_ANALYZER_MAP: Final[dict[str, str]] = {
    "python": "ruff",
    "javascript": "eslint",
    "typescript": "eslint",
    "ruff": "ruff",
    "bandit": "bandit",
    "eslint": "eslint",
    "radon": "radon",
}


@dataclass(frozen=True, slots=True)
class QualityRule:
    language: str
    analyzer: str
    rule_id: str
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class QualityProfile:
    language: str
    rules: tuple[QualityRule, ...] = ()


@dataclass(frozen=True, slots=True)
class QualityGatePolicy:
    version: int = 1
    thresholds: QualityGateConfig = field(default_factory=QualityGateConfig)
    profiles: tuple[QualityProfile, ...] = ()

    @property
    def enabled_rules(self) -> tuple[QualityRule, ...]:
        return tuple(rule for profile in self.profiles for rule in profile.rules if rule.enabled)


@dataclass(frozen=True, slots=True)
class SonarProfileImportReport:
    language: str
    profile_name: str | None
    mapped: int
    unsupported: tuple[str, ...]
    invalid: tuple[str, ...]
    profile: QualityProfile


def parse_sonar_profile_xml(
    payload: bytes, *, max_bytes: int = 1_048_576
) -> SonarProfileImportReport:
    """Parse a SonarQube quality-profile backup without resolving entities."""
    if len(payload) > max_bytes:
        raise ValueError("quality profile XML exceeds size limit")
    try:
        root = ElementTree.fromstring(
            payload,
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
    except (ElementTree.ParseError, DefusedXmlException) as error:
        raise ValueError("invalid quality profile XML") from error
    language, name = _parse_profile_metadata(root)
    mapped_rules, unsupported, invalid = _parse_profile_rules(root, language)
    profile = QualityProfile(language, tuple(mapped_rules))
    return SonarProfileImportReport(
        language, name, len(mapped_rules), tuple(unsupported), tuple(invalid), profile
    )


def _parse_profile_metadata(root: Any) -> tuple[str, str | None]:
    language = _node_value(root, "language").strip() or "unknown"
    name = _node_value(root, "name") or None
    return language, name


def _node_value(node: Any, field_name: str) -> str:
    return (node.findtext(field_name) or node.attrib.get(field_name) or "").strip()


def _parse_profile_rules(
    root: Any, language: str
) -> tuple[list[QualityRule], list[str], list[str]]:
    mapped_rules: list[QualityRule] = []
    unsupported: list[str] = []
    invalid: list[str] = []
    for node in root.findall(".//rule"):
        key, analyzer, rule_id = _parse_quality_rule_key(node)
        if analyzer is None or rule_id is None:
            invalid.append(key)
        elif analyzer not in SONAR_ANALYZER_MAP or not rule_id:
            unsupported.append(key)
        else:
            mapped_rules.append(QualityRule(language, SONAR_ANALYZER_MAP[analyzer], rule_id, True))
    return mapped_rules, unsupported, invalid


def _parse_quality_rule_key(node: Any) -> tuple[str, str | None, str | None]:
    key = _node_value(node, "key")
    repository_key = _node_value(node, "repositoryKey")
    if repository_key and ":" not in key:
        key = f"{repository_key}:{key}"
    if ":" not in key:
        return key or "missing-key", None, None
    analyzer, rule_id = key.split(":", 1)
    return key, analyzer.casefold(), rule_id
