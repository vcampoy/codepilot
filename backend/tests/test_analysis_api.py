from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from codepilot.core.settings import Settings
from codepilot.domain.analysis import AnalysisResult
from codepilot.llm.contracts import DeterministicEvidence, EnrichmentResult, EnrichmentTask
from codepilot.main import create_app
from codepilot.repositories.analysis import (
    InMemoryAnalysisRepository,
    PostgresAnalysisRepository,
)
from codepilot.services.analysis import AnalysisService
from codepilot.services.repository_ingestion import RepositorySnapshot


@dataclass
class ApiIngestion:
    @asynccontextmanager
    async def ingest(self, _url: str) -> AsyncIterator[RepositorySnapshot]:
        yield RepositorySnapshot(
            repository_path=Path("C:/isolated/repository"),
            commit_sha="b" * 40,
            default_branch="main",
            primary_languages=("Python",),
            file_count=3,
            source_size_bytes=900,
        )


@dataclass
class ApiAnalyzer:
    async def analyze(self, _snapshot: RepositorySnapshot) -> AnalysisResult:
        return AnalysisResult(analyzed_file_count=3, source_lines=20, findings=())


@dataclass
class ApiQueue:
    analysis_ids: list[object]

    def enqueue(self, analysis_id: object) -> None:
        self.analysis_ids.append(analysis_id)


class ApiLlmGateway:
    async def enrich(
        self, task: EnrichmentTask, evidence: DeterministicEvidence
    ) -> EnrichmentResult:
        return EnrichmentResult(
            task=task,
            analysis_id=evidence.analysis_id,
            enabled=True,
            ai_generated=True,
            text="Evidence-backed explanation.",
            citations=["score:finding_count"],
            model="test-model",
            provider="test",
        )


def make_service() -> tuple[InMemoryAnalysisRepository, AnalysisService]:
    repository = InMemoryAnalysisRepository()
    service = AnalysisService(repository, ApiIngestion(), ApiAnalyzer(), ApiQueue([]))
    return repository, service


def test_analysis_request_returns_202_and_status_endpoint_reads_persisted_record() -> None:
    _, service = make_service()
    with TestClient(create_app(analysis_service=service)) as client:
        accepted = client.post(
            "/api/v1/analyses",
            json={"repository_url": "https://github.com/example/project.git"},
        )
        analysis_id = accepted.json()["analysis_id"]
        status = client.get(f"/api/v1/analyses/{analysis_id}")

    assert accepted.status_code == 202
    assert accepted.json()["status"] == "queued"
    assert status.status_code == 200
    assert status.json()["analysis_id"] == analysis_id
    assert status.json()["status"] == "queued"


def test_summary_endpoint_exposes_persisted_metrics_after_worker_completion() -> None:
    repository, service = make_service()
    with TestClient(create_app(analysis_service=service)) as client:
        accepted = client.post(
            "/api/v1/analyses",
            json={"repository_url": "https://github.com/example/project.git"},
        )
        analysis_id = accepted.json()["analysis_id"]
        asyncio.run(service.process_analysis(UUID(analysis_id)))
        summary = client.get(f"/api/v1/analyses/{analysis_id}/summary")

    assert repository is not None
    assert summary.status_code == 200
    assert summary.json()["status"] == "completed"
    assert summary.json()["summary"] == {
        "analyzed_file_count": 3,
        "source_lines": 20,
        "finding_count_by_severity": {},
        "duration_seconds": summary.json()["summary"]["duration_seconds"],
    }


def test_enrichment_endpoint_labels_ai_output_and_uses_completed_evidence() -> None:
    _, service = make_service()
    with TestClient(create_app(analysis_service=service, llm_gateway=ApiLlmGateway())) as client:
        accepted = client.post(
            "/api/v1/analyses",
            json={"repository_url": "https://github.com/example/project.git"},
        )
        analysis_id = accepted.json()["analysis_id"]
        asyncio.run(service.process_analysis(UUID(analysis_id)))
        enrichment = client.post(
            f"/api/v1/analyses/{analysis_id}/enrichment/file-risk"
        )

    assert enrichment.status_code == 200
    assert enrichment.json()["ai_generated"] is True
    assert enrichment.json()["citations"] == ["score:finding_count"]


def test_unknown_analysis_is_a_safe_not_found_error() -> None:
    _, service = make_service()
    with TestClient(create_app(analysis_service=service)) as client:
        response = client.get("/api/v1/analyses/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "analysis_not_found"


def test_default_application_uses_configured_postgres_analysis_repository() -> None:
    app = create_app(
        Settings(
            database_url=SecretStr(
                "postgresql+asyncpg://codepilot:codepilot@localhost:5432/codepilot"
            )
        )
    )

    assert isinstance(app.state.analysis_repository, PostgresAnalysisRepository)


def test_production_repository_is_disposed_by_fastapi_lifespan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codepilot import main as main_module

    class DisposableRepository(InMemoryAnalysisRepository):
        disposed = False

        async def dispose(self) -> None:
            self.disposed = True

    repository = DisposableRepository()
    monkeypatch.setattr(
        main_module,
        "PostgresAnalysisRepository",
        lambda _database_url: repository,
    )

    with TestClient(create_app(Settings())):
        pass

    assert repository.disposed is True


def test_injected_analysis_repository_is_not_disposed_by_fastapi_lifespan() -> None:
    class DisposableRepository(InMemoryAnalysisRepository):
        disposed = False

        async def dispose(self) -> None:
            self.disposed = True

    repository = DisposableRepository()
    service = AnalysisService(repository, ApiIngestion(), ApiAnalyzer(), ApiQueue([]))

    with TestClient(create_app(analysis_service=service)):
        pass

    assert repository.disposed is False


def test_prompt05_alembic_migration_is_present_for_predeployment_schema_setup() -> None:
    backend_root = Path(__file__).parents[1]
    migration_root = backend_root / "alembic"
    revisions = list((migration_root / "versions").glob("*.py"))

    assert (backend_root / "alembic.ini").is_file()
    assert (migration_root / "env.py").is_file()
    assert any("codepilot_analyses" in revision.read_text() for revision in revisions)


def test_prompt05_deployment_copies_migrations_and_runs_them_before_app_workers() -> None:
    repository_root = Path(__file__).parents[2]
    dockerfile = (repository_root / "backend" / "Dockerfile").read_text()
    compose = (repository_root / "docker-compose.yml").read_text()

    assert "COPY alembic.ini ./" in dockerfile
    assert "COPY alembic ./alembic" in dockerfile
    assert "  migration:" in compose
    assert "command: alembic upgrade head" in compose
    assert "condition: service_completed_successfully" in compose
    assert "  beat:" in compose
    assert "--schedule=/tmp/celerybeat-schedule" in compose
