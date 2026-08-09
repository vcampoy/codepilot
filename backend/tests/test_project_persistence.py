from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from codepilot.domain.analysis import AnalysisResult
from codepilot.main import create_app
from codepilot.repositories.analysis import InMemoryAnalysisRepository
from codepilot.services.analysis import AnalysisService
from codepilot.services.repository_ingestion import RepositorySnapshot


class Queue:
    def enqueue(self, _analysis_id: UUID) -> None:
        return None


class Ingestion:
    async def __aenter__(self) -> RepositorySnapshot:
        return RepositorySnapshot(Path("C:/repo"), "a" * 40, "main", (), 0, 0)

    async def __aexit__(self, *_args: object) -> None:
        return None

    def ingest(self, _url: str) -> Ingestion:
        return self


class Analyzer:
    async def analyze(self, _snapshot: RepositorySnapshot) -> AnalysisResult:
        return AnalysisResult(0, 0, ())


def _app() -> tuple[TestClient, InMemoryAnalysisRepository]:
    repository = InMemoryAnalysisRepository()
    service = AnalysisService(repository, Ingestion(), Analyzer(), Queue())
    return TestClient(create_app(analysis_service=service)), repository


def test_analysis_is_linked_to_workspace_project_and_project_catalog_is_paginated() -> None:
    client, repository = _app()
    with client:
        accepted = client.post(
            "/api/v1/analyses",
            json={"repository_url": "https://github.com/acme/widget.git"},
            headers={"X-Workspace-ID": "team-a"},
        )
        analysis_id = accepted.json()["analysis_id"]
        projects = client.get(
            "/api/v1/projects?limit=10&offset=0", headers={"X-Workspace-ID": "team-a"}
        )
        runs = client.get(
            f"/api/v1/projects/{projects.json()['items'][0]['project_id']}/analyses",
            headers={"X-Workspace-ID": "team-a"},
        )

    record = asyncio.run(repository.get(UUID(analysis_id), "team-a"))
    assert record is not None
    assert accepted.json()["project_id"] == str(record.project_id)
    assert projects.status_code == 200
    assert projects.json()["total"] == 1
    assert runs.json()["items"][0]["analysis_id"] == analysis_id


def test_project_catalog_does_not_cross_workspace_boundary() -> None:
    client, _ = _app()
    with client:
        client.post(
            "/api/v1/analyses",
            json={"repository_url": "https://github.com/acme/widget.git"},
            headers={"X-Workspace-ID": "team-a"},
        )
        hidden = client.get("/api/v1/projects", headers={"X-Workspace-ID": "team-b"})
    assert hidden.json()["total"] == 0


def test_reusing_repository_identity_keeps_one_project_and_refreshes_timestamp() -> None:
    repository = InMemoryAnalysisRepository()
    first = asyncio.run(
        repository.get_or_create_project("https://github.com/acme/widget.git", "team-a")
    )
    second = asyncio.run(
        repository.get_or_create_project("https://github.com/acme/widget/", "team-a")
    )
    assert first.project_id == second.project_id
    assert second.updated_at >= first.updated_at
