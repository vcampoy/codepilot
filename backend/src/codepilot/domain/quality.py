# ruff: noqa: E501
"""Project quality-gate policies and defensive SonarQube profile imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from typing import Final
from xml.etree import ElementTree

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
    upper = payload.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper or b"SYSTEM" in upper or b"PUBLIC" in upper:
        raise ValueError("DTD and external entities are not allowed")
    try:
        root = ElementTree.parse(BytesIO(payload)).getroot()
    except ElementTree.ParseError as error:
        raise ValueError("invalid quality profile XML") from error
    language = (root.findtext("language") or root.attrib.get("language") or "unknown").strip()
    name = root.findtext("name") or root.attrib.get("name") or None
    mapped_rules: list[QualityRule] = []
    unsupported: list[str] = []
    invalid: list[str] = []
    for node in root.findall(".//rule"):
        key = (node.findtext("key") or node.attrib.get("key") or "").strip()
        repository_key = (
            node.findtext("repositoryKey") or node.attrib.get("repositoryKey") or ""
        ).strip()
        if repository_key and ":" not in key:
            key = f"{repository_key}:{key}"
        if not key or ":" not in key:
            invalid.append(key or "missing-key")
            continue
        analyzer, rule_id = key.split(":", 1)
        mapped_analyzer = SONAR_ANALYZER_MAP.get(analyzer.lower())
        if mapped_analyzer is None or not rule_id:
            unsupported.append(key)
            continue
        mapped_rules.append(QualityRule(language, mapped_analyzer, rule_id, True))
    profile = QualityProfile(language, tuple(mapped_rules))
    return SonarProfileImportReport(
        language, name, len(mapped_rules), tuple(unsupported), tuple(invalid), profile
    )

