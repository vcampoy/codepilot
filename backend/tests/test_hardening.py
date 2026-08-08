"""Security and public-MVP hardening tests."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from codepilot.core.settings import Settings
from codepilot.main import create_app
from codepilot.repositories.analysis import InMemoryAnalysisRepository
from codepilot.services.analysis import AnalysisService


def make_app(rate_limit_requests: int = 10, workspace_quota: int = 100) -> FastAPI:
    repository = InMemoryAnalysisRepository()

    class Queue:
        def enqueue(self, _analysis_id: object) -> None:
            return None

    class Ingestion:
        def ingest(self, _url: str) -> object:
            raise AssertionError("ingestion is not expected in API hardening tests")

    class Analyzer:
        async def analyze(self, _snapshot: object) -> object:
            raise AssertionError("analyzer is not expected in API hardening tests")

    service = AnalysisService(repository, Ingestion(), Analyzer(), Queue())  # type: ignore[arg-type]
    settings = Settings(
        auth_required=True,
        auth_api_key=SecretStr("test-api-key"),
        rate_limit_requests=rate_limit_requests,
        rate_limit_window_seconds=60,
        workspace_analysis_quota=workspace_quota,
    )
    return create_app(settings, analysis_service=service)


def test_authenticated_workspaces_cannot_read_each_others_analyses() -> None:
    with TestClient(make_app()) as client:
        missing = client.post(
            "/api/v1/analyses",
            json={"repository_url": "https://github.com/acme/project.git"},
        )
        created = client.post(
            "/api/v1/analyses",
            headers={"X-API-Key": "test-api-key", "X-Workspace-ID": "workspace-a"},
            json={"repository_url": "https://github.com/acme/project.git"},
        )
        analysis_id = created.json()["analysis_id"]
        forbidden = client.get(
            f"/api/v1/analyses/{analysis_id}",
            headers={"X-API-Key": "test-api-key", "X-Workspace-ID": "workspace-b"},
        )
        forbidden_files = client.get(
            f"/api/v1/analyses/{analysis_id}/files",
            headers={"X-API-Key": "test-api-key", "X-Workspace-ID": "workspace-b"},
        )

    assert missing.status_code == 401
    assert forbidden.status_code == 404
    assert forbidden_files.status_code == 404


def test_health_readiness_liveness_and_security_headers() -> None:
    with TestClient(make_app()) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")

    assert live.json() == {"status": "ok"}
    assert ready.json() == {"status": "ok"}
    assert live.headers["x-content-type-options"] == "nosniff"
    assert live.headers["x-frame-options"] == "DENY"


def test_rate_limit_returns_retryable_429() -> None:
    app = make_app(rate_limit_requests=1)
    with TestClient(app) as client:
        responses = [
            client.get("/api/v1/"),
            client.get("/api/v1/"),
        ]

    assert responses[0].status_code == 200
    assert responses[1].status_code == 429
    assert responses[1].headers["retry-after"]


def test_workspace_quota_rejects_the_next_analysis() -> None:
    with TestClient(make_app(workspace_quota=1)) as client:
        headers = {"X-API-Key": "test-api-key", "X-Workspace-ID": "workspace-a"}
        first = client.post(
            "/api/v1/analyses",
            headers=headers,
            json={"repository_url": "https://github.com/acme/project.git"},
        )
        second = client.post(
            "/api/v1/analyses",
            headers=headers,
            json={"repository_url": "https://github.com/acme/project.git"},
        )

    assert first.status_code == 202
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "workspace_quota_exceeded"
