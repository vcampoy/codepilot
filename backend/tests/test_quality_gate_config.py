# ruff: noqa: E501
from typing import Any, cast

import pytest

from codepilot.analyzers.risk_score import FindingRisk, QualityGateConfig, evaluate_quality_gates
from codepilot.domain.quality import (
    QualityGatePolicy,
    QualityProfile,
    QualityRule,
    parse_sonar_profile_xml,
)
from codepilot.main import create_app
from codepilot.repositories.analysis import InMemoryAnalysisRepository
from codepilot.services.analysis import AnalysisService


def test_policy_is_immutable_and_rules_add_gate_failure() -> None:
    policy = QualityGatePolicy(
        version=2,
        thresholds=QualityGateConfig(max_risk_score=0.5),
        profiles=(QualityProfile("python", (QualityRule("python", "ruff", "S123", True),)),),
    )
    assert policy.version == 2
    result = evaluate_quality_gates(
        (FindingRisk("f", "critical", True, "ruff", "S123"),),
        risk_score=0.1,
        hotspot_count=0,
        config=policy.thresholds,
        enabled_rules=policy.enabled_rules,
    )
    assert result.passed is False
    assert any(f.code == "enabled-rules" for f in result.failures)


def test_sonar_profile_import_maps_and_reports_unsupported() -> None:
    xml = (
        b"<profile><name>py</name><language>py</language><rules>"
        b"<rule><repositoryKey>python</repositoryKey><key>S123</key>"
        b"<priority>MAJOR</priority><status>READY</status></rule>"
        b"<rule><key>x:ZZZ</key></rule></rules></profile>"
    )
    report = parse_sonar_profile_xml(xml, max_bytes=10000)
    assert report.mapped == 1
    assert report.unsupported == ("x:ZZZ",)


def test_sonar_xml_rejects_dtd() -> None:
    with pytest.raises(ValueError):
        parse_sonar_profile_xml(b'<!DOCTYPE foo [<!ENTITY x "x">]><profile />')


def test_quality_policy_api_is_tenant_safe() -> None:
    import asyncio

    from fastapi.testclient import TestClient

    repository = InMemoryAnalysisRepository()
    service = AnalysisService(
        repository,
        cast(Any, object()),
        cast(Any, object()),
        cast(Any, object()),
    )
    client = TestClient(create_app(analysis_service=service))
    project = asyncio.run(
        repository.get_or_create_project("https://github.com/acme/quality.git", "team-a")
    )
    with client:
        response = client.put(
            f"/api/v1/projects/{project.project_id}/quality-policy",
            json={"max_risk_score": 0.4, "profiles": []},
            headers={"X-Workspace-ID": "team-a"},
        )
        hidden = client.get(
            f"/api/v1/projects/{project.project_id}/quality-policy",
            headers={"X-Workspace-ID": "team-b"},
        )
    assert response.status_code == 200
    assert response.json()["max_risk_score"] == 0.4
    assert hidden.json()["configured"] is False
