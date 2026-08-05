"""Mocked GitHub App, webhook, and pull-request analysis tests."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from codepilot.github.client import GitHubAppAuthenticator, GitHubClient
from codepilot.github.contracts import FindingSnapshot, GitHubResponse
from codepilot.github.diff_analysis import (
    build_check_run_payload,
    compare_pull_request,
    parse_added_lines,
)
from codepilot.github.webhooks import (
    GitHubWebhookService,
    InMemoryWebhookEventStore,
    InvalidWebhookSignatureError,
)
from codepilot.main import create_app


def test_webhook_signature_is_verified_and_replay_is_idempotent() -> None:
    secret = b"webhook-secret"
    payload = {
        "action": "opened",
        "repository": {"full_name": "acme/project"},
        "pull_request": {"number": 7},
        "installation": {"id": 42},
    }
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    dispatched: list[str] = []

    async def dispatch(event: object) -> None:
        dispatched.append(event.delivery_id)  # type: ignore[attr-defined]

    service = GitHubWebhookService(secret, InMemoryWebhookEventStore(), dispatch)

    first = asyncio.run(
        service.handle(
            event_name="pull_request",
            delivery_id="delivery-1",
            signature=signature,
            body=body,
        )
    )
    replay = asyncio.run(
        service.handle(
            event_name="pull_request",
            delivery_id="delivery-1",
            signature=signature,
            body=body,
        )
    )

    assert first.duplicate is False
    assert replay.duplicate is True
    assert dispatched == ["delivery-1"]


def test_invalid_webhook_signature_is_rejected() -> None:
    service = GitHubWebhookService(b"secret", InMemoryWebhookEventStore(), lambda _: None)

    with pytest.raises(InvalidWebhookSignatureError):
        asyncio.run(
            service.handle(
                event_name="push",
                delivery_id="delivery-1",
                signature="sha256=invalid",
                body=b"{}",
            )
        )


def test_webhook_http_endpoint_rejects_invalid_signature() -> None:
    service = GitHubWebhookService(b"secret", InMemoryWebhookEventStore(), lambda _: None)

    with TestClient(create_app(github_webhook_service=service)) as client:
        response = client.post(
            "/api/v1/github/webhook",
            headers={
                "X-GitHub-Event": "push",
                "X-GitHub-Delivery": "delivery-1",
                "X-Hub-Signature-256": "sha256=invalid",
            },
            content=b"{}",
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_github_signature"


def test_pull_request_comparison_reports_delta_and_quality_gate() -> None:
    baseline = (FindingSnapshot(finding_id="F-1", path="src/a.py", severity="high"),)
    current = (
        FindingSnapshot(finding_id="F-1", path="src/a.py", severity="high"),
        FindingSnapshot(finding_id="F-2", path="src/new.py", severity="critical"),
    )

    comparison = compare_pull_request(
        baseline,
        current,
        baseline_hotspots=("src/a.py",),
        current_hotspots=("src/a.py", "src/new.py"),
        baseline_risk=0.42,
        current_risk=0.71,
        max_new_critical_findings=0,
        max_risk_score=0.65,
        max_new_hotspots=0,
    )

    assert [finding.finding_id for finding in comparison.new_findings] == ["F-2"]
    assert comparison.resolved_findings == ()
    assert comparison.risk_delta == 0.29
    assert comparison.new_hotspots == ("src/new.py",)
    assert comparison.quality_gate.passed is False
    assert {failure.code for failure in comparison.quality_gate.failures} == {
        "critical-findings",
        "risk-score",
        "hotspots",
    }


def test_diff_parser_returns_only_added_line_ranges() -> None:
    diff = """diff --git a/src/a.py b/src/a.py
@@ -1,2 +1,4 @@
 line one
+new one
+new two
 line two
"""

    assert parse_added_lines(diff) == {"src/a.py": ((2, 3),)}


def test_app_authenticator_uses_short_lived_claims_without_logging_token() -> None:
    claims: dict[str, object] = {}

    def encode(payload: dict[str, object], _key: str, algorithm: str) -> str:
        claims.update(payload)
        assert algorithm == "RS256"
        return "signed-token"

    authenticator = GitHubAppAuthenticator(
        app_id=123,
        private_key="private-key",
        encode=encode,
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert authenticator.create_app_token() == "signed-token"
    assert claims == {"iat": 1767225540, "exp": 1767226140, "iss": "123"}


def test_github_client_retries_rate_limit_and_creates_concise_check() -> None:
    responses = [
        GitHubResponse(429, {"Retry-After": "0"}, {}),
        GitHubResponse(201, {}, {"id": 99}),
    ]
    calls: list[tuple[str, str]] = []

    async def request(method: str, path: str, **_: object) -> GitHubResponse:
        calls.append((method, path))
        return responses.pop(0)

    async def no_sleep(_: float) -> None:
        return None

    client = GitHubClient(request=request, sleep=no_sleep, max_retries=1)
    result = asyncio.run(
        client.create_check_run(
            "acme/project",
            "abc123",
            {
                "name": "CodePilot",
                "head_sha": "abc123",
                "status": "completed",
                "conclusion": "failure",
                "output": {"title": "CodePilot quality gate", "summary": "2 issues"},
            },
            token="installation-token",
        )
    )

    assert result == {"id": 99}
    assert calls == [
        ("POST", "/repos/acme/project/check-runs"),
        ("POST", "/repos/acme/project/check-runs"),
    ]


def test_check_run_payload_is_concise_and_links_to_analysis() -> None:
    comparison = compare_pull_request(
        (),
        (FindingSnapshot(finding_id="F-1", path="src/a.py", severity="high"),),
        baseline_hotspots=(),
        current_hotspots=(),
        baseline_risk=0.1,
        current_risk=0.4,
    )

    payload = build_check_run_payload(
        comparison,
        head_sha="abc123",
        details_url="https://codepilot.example/analyses/1",
    )

    assert payload["conclusion"] == "success"
    assert payload["details_url"] == "https://codepilot.example/analyses/1"
    assert "inline" not in str(payload).lower()
