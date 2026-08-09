from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from codepilot.analyzers.risk_score import RiskAssessment
from codepilot.domain.analysis import (
    AnalysisHistoryRecord,
    AnalysisRecord,
    AnalysisResult,
    AnalysisStatus,
    AnalysisSummary,
    ProjectRecord,
)
from codepilot.main import create_app
from codepilot.repositories.analysis import InMemoryAnalysisRepository
from codepilot.services.analysis import AnalysisService
from codepilot.services.repository_ingestion import RepositorySnapshot


class HistoryQueue:
    def enqueue(self, _analysis_id: UUID) -> None:
        return None


class HistoryIngestion:
    async def __aenter__(self) -> RepositorySnapshot:
        return RepositorySnapshot(Path("C:/repo"), "a" * 40, "main", (), 0, 0)

    async def __aexit__(self, *_args: object) -> None:
        return None

    def ingest(self, _url: str) -> HistoryIngestion:
        return self


class HistoryAnalyzer:
    async def analyze(self, _snapshot: RepositorySnapshot) -> AnalysisResult:
        return AnalysisResult(2, 20, ())


def completed_summary(score: float, findings: int, files: int, duration: float) -> AnalysisSummary:
    return AnalysisSummary(
        analyzed_file_count=files,
        source_lines=20,
        finding_count_by_severity={"warning": findings},
        duration_seconds=duration,
        risk_assessment=RiskAssessment(
            score, "high", "1.0", {"findings": score}, {"findings": 1.0}
        ),
    )


async def complete_record(
    repository: InMemoryAnalysisRepository,
    url: str,
    workspace: str,
    *,
    score: float = 0.8,
    findings: int = 3,
    files: int = 2,
    duration: float = 1.2,
) -> UUID:
    record = await repository.create(url, workspace)
    token = await repository.claim_running(record.analysis_id)
    assert token is not None
    await repository.complete(
        record.analysis_id,
        AnalysisResult(files, 20, ()),
        completed_summary(score, findings, files, duration),
        lease_token=token,
    )
    return record.analysis_id


def test_history_lists_completed_runs_with_overview_kpis_and_pagination() -> None:
    async def run() -> tuple[tuple[AnalysisHistoryRecord, ...], int, tuple[UUID, UUID, UUID]]:
        repository = InMemoryAnalysisRepository()
        first = await complete_record(repository, "https://github.com/acme/first.git", "team-a")
        second = await complete_record(repository, "https://github.com/acme/second.git", "team-a")
        queued = await repository.create("https://github.com/acme/queued.git", "team-a")
        history, total = await repository.list_history("team-a", limit=1, offset=0)
        return history, total, (first, second, queued.analysis_id)

    history, total, ids = asyncio.run(run())
    assert total == 2
    assert len(history) == 1
    assert history[0].analysis_id == ids[1]
    assert history[0].repository_name == "second"
    assert history[0].finding_count == 3


def test_delete_analysis_rejects_running_runs_and_preserves_project() -> None:
    async def run() -> tuple[AnalysisStatus, AnalysisRecord | None, ProjectRecord]:
        repository = InMemoryAnalysisRepository()
        record = await repository.create("https://github.com/acme/widget.git", "team-a")
        with pytest.raises(ValueError, match="completed"):
            await repository.delete_analysis(record.analysis_id, "team-a")
        stored = await repository.get(record.analysis_id, "team-a")
        project = await repository.get_or_create_project(record.repository_url, "team-a")
        return record.status, stored, project

    status, stored, project = asyncio.run(run())
    assert status is AnalysisStatus.QUEUED
    assert stored is not None
    assert project.name == "widget"


def test_history_api_is_workspace_scoped_and_delete_returns_no_content() -> None:
    async def prepare(repository: InMemoryAnalysisRepository) -> UUID:
        return await complete_record(repository, "https://github.com/acme/widget.git", "team-a")

    repository = InMemoryAnalysisRepository()
    analysis_id = asyncio.run(prepare(repository))
    service = AnalysisService(repository, HistoryIngestion(), HistoryAnalyzer(), HistoryQueue())
    with TestClient(create_app(analysis_service=service)) as client:
        history = client.get("/api/v1/analyses/history", headers={"X-Workspace-ID": "team-a"})
        hidden = client.get("/api/v1/analyses/history", headers={"X-Workspace-ID": "team-b"})
        deleted = client.delete(
            f"/api/v1/analyses/{analysis_id}", headers={"X-Workspace-ID": "team-a"}
        )
        missing = client.delete(
            f"/api/v1/analyses/{analysis_id}", headers={"X-Workspace-ID": "team-a"}
        )

    assert history.status_code == 200
    assert history.json()["items"][0]["analysis_id"] == str(analysis_id)
    assert history.json()["items"][0]["finding_count"] == 3
    assert hidden.json()["total"] == 0
    assert deleted.status_code == 204
    assert missing.status_code == 404
