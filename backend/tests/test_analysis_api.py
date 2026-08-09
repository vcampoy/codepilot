from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from pydantic import SecretStr

from codepilot.analyzers.risk_score import RiskScoreConfig, calculate_risk
from codepilot.api.v1.analyses import _quality_gate_payload
from codepilot.core.errors import ApplicationError
from codepilot.core.settings import Settings
from codepilot.domain.analysis import (
    AnalysisFinding,
    AnalysisResult,
    AnalysisSummary,
    AnalyzerOutcome,
)
from codepilot.domain.insights import FileInsight
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
class FindingsAnalyzer:
    async def analyze(self, _snapshot: RepositorySnapshot) -> AnalysisResult:
        return AnalysisResult(
            analyzed_file_count=3,
            source_lines=20,
            findings=(
                AnalysisFinding(
                    path="src/main.py",
                    rule_id="PY001",
                    severity="warning",
                    message="Avoid this pattern.",
                    start_line=4,
                    end_line=4,
                    analyzer="python.ruff",
                    category="quality",
                    title="Avoid this pattern",
                    evidence="The rule matched this expression.",
                    remediation="Refactor the expression.",
                ),
            ),
            analyzer_outcomes=(
                AnalyzerOutcome(
                    analyzer="generic.file-metrics",
                    tool="generic.file-metrics",
                    version="1.0.0",
                    status="succeeded",
                    duration_seconds=0.01,
                    generic=True,
                ),
            ),
        )


@dataclass
class InsightsAnalyzer:
    async def analyze(self, _snapshot: RepositorySnapshot) -> AnalysisResult:
        risk = calculate_risk({"finding_severity": 0.4}, RiskScoreConfig())
        return AnalysisResult(
            analyzed_file_count=3,
            source_lines=20,
            findings=(
                AnalysisFinding(
                    path="src/main.py",
                    rule_id="PY001",
                    severity="warning",
                    message="Avoid this pattern.",
                    start_line=4,
                    end_line=4,
                ),
            ),
            file_insights=(FileInsight("src/main.py", 0.8, risk, {"finding_severity": 0.4}),),
        )


@dataclass
class PagedInsightsAnalyzer:
    async def analyze(self, _snapshot: RepositorySnapshot) -> AnalysisResult:
        return AnalysisResult(
            analyzed_file_count=3,
            source_lines=20,
            findings=(),
            file_insights=(
                FileInsight("src/z.py", 0.2, None, {"finding_severity": 0.1}),
                FileInsight("src/a.py", 0.9, None, {"finding_severity": 0.9}),
                FileInsight("src/m.py", 0.5, None, {"finding_severity": 0.5}),
            ),
        )


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
        "analyzer_outcomes": [],
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
        enrichment = client.post(f"/api/v1/analyses/{analysis_id}/enrichment/file-risk")

    assert enrichment.status_code == 200
    assert enrichment.json()["ai_generated"] is True
    assert enrichment.json()["citations"] == ["score:finding_count"]


def test_findings_endpoint_returns_persisted_findings_and_summary_outcomes() -> None:
    repository = InMemoryAnalysisRepository()
    service = AnalysisService(repository, ApiIngestion(), FindingsAnalyzer(), ApiQueue([]))
    with TestClient(create_app(analysis_service=service)) as client:
        accepted = client.post(
            "/api/v1/analyses",
            json={"repository_url": "https://github.com/example/project.git"},
        )
        analysis_id = accepted.json()["analysis_id"]
        asyncio.run(service.process_analysis(UUID(analysis_id)))
        findings = client.get(f"/api/v1/analyses/{analysis_id}/findings")
        summary = client.get(f"/api/v1/analyses/{analysis_id}/summary")

    assert findings.status_code == 200
    assert findings.json() == [
        {
            "path": "src/main.py",
            "rule_id": "PY001",
            "analyzer": "python.ruff",
            "severity": "warning",
            "message": "Avoid this pattern.",
            "start_line": 4,
            "end_line": 4,
            "category": "quality",
            "title": "Avoid this pattern",
            "evidence": "The rule matched this expression.",
            "remediation": "Refactor the expression.",
            "source_context": None,
        }
    ]
    assert summary.json()["summary"]["analyzer_outcomes"][0]["analyzer"] == "generic.file-metrics"


def _request_insights_endpoints() -> tuple[Response, Response, Response]:
    repository = InMemoryAnalysisRepository()
    service = AnalysisService(repository, ApiIngestion(), InsightsAnalyzer(), ApiQueue([]))
    with TestClient(create_app(analysis_service=service)) as client:
        accepted = client.post(
            "/api/v1/analyses",
            json={"repository_url": "https://github.com/example/project.git"},
        )
        analysis_id = accepted.json()["analysis_id"]
        asyncio.run(service.process_analysis(UUID(analysis_id)))
        summary = client.get(f"/api/v1/analyses/{analysis_id}/summary")
        hotspots = client.get(f"/api/v1/analyses/{analysis_id}/hotspots")
        detail = client.get(
            f"/api/v1/analyses/{analysis_id}/files/detail",
            params={"path": "src/main.py"},
        )

    return summary, hotspots, detail


def test_insights_summary_exposes_risk_and_quality_gate() -> None:
    summary, _, _ = _request_insights_endpoints()

    assert summary.json()["summary"]["risk_assessment"]["score"] == 0.4
    assert summary.json()["summary"]["quality_gate"]["passed"] is True
    assert summary.json()["summary"]["quality_gate"]["configured"] is False
    assert summary.json()["summary"]["quality_gate"]["status"] == "not_configured"
    assert summary.json()["summary"]["quality_gate"]["observed"] == {
        "new_critical_findings": 0,
        "risk_score": 0.4,
        "new_hotspots": 1,
    }
    assert summary.json()["summary"]["quality_gate"]["thresholds"] == {
        "max_new_critical_findings": None,
        "max_risk_score": None,
        "max_new_hotspots": None,
    }


def test_quality_gate_payload_raises_application_error_when_gate_is_missing() -> None:
    summary = AnalysisSummary(0, 0, {}, 0.0)

    with pytest.raises(ApplicationError) as error:
        _quality_gate_payload(summary)

    assert error.value.code == "quality_gate_unavailable"
    assert error.value.message == "Quality gate data is unavailable."
    assert error.value.status_code == 500


def test_insights_hotspots_endpoint_exposes_ranked_file() -> None:
    _, hotspots, _ = _request_insights_endpoints()

    assert hotspots.json()[0]["path"] == "src/main.py"


def test_insights_file_detail_endpoint_exposes_findings() -> None:
    _, _, detail = _request_insights_endpoints()

    assert detail.json()["path"] == "src/main.py"
    assert len(detail.json()["findings"]) == 1


def test_files_endpoint_returns_paginated_sorted_insights() -> None:
    repository = InMemoryAnalysisRepository()
    service = AnalysisService(repository, ApiIngestion(), PagedInsightsAnalyzer(), ApiQueue([]))
    with TestClient(create_app(analysis_service=service)) as client:
        accepted = client.post(
            "/api/v1/analyses",
            json={"repository_url": "https://github.com/example/project.git"},
        )
        analysis_id = accepted.json()["analysis_id"]
        asyncio.run(service.process_analysis(UUID(analysis_id)))
        page = client.get(
            f"/api/v1/analyses/{analysis_id}/files",
            params={"limit": 2, "offset": 1},
        )

    assert page.status_code == 200
    assert page.json()["total"] == 3
    assert page.json()["limit"] == 2
    assert page.json()["offset"] == 1
    assert [item["path"] for item in page.json()["items"]] == ["src/m.py", "src/z.py"]


def test_second_analysis_uses_previous_completed_run_as_baseline() -> None:
    repository = InMemoryAnalysisRepository()
    service = AnalysisService(repository, ApiIngestion(), InsightsAnalyzer(), ApiQueue([]))
    with TestClient(create_app(analysis_service=service)) as client:
        first = client.post(
            "/api/v1/analyses",
            json={"repository_url": "https://github.com/example/project.git"},
        )
        first_id = first.json()["analysis_id"]
        asyncio.run(service.process_analysis(UUID(first_id)))
        second = client.post(
            "/api/v1/analyses",
            json={"repository_url": "https://github.com/example/project.git"},
        )
        second_id = second.json()["analysis_id"]
        asyncio.run(service.process_analysis(UUID(second_id)))
        summary = client.get(f"/api/v1/analyses/{second_id}/summary")

    assert summary.json()["summary"]["baseline_analysis_id"] == first_id


def test_unknown_analysis_is_a_safe_not_found_error() -> None:
    _, service = make_service()
    with TestClient(create_app(analysis_service=service)) as client:
        response = client.get("/api/v1/analyses/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "analysis_not_found"


def test_global_analyzer_preflight_marks_sarif_as_not_requested() -> None:
    _, service = make_service()
    with TestClient(create_app(analysis_service=service)) as client:
        response = client.get("/api/v1/analyses/analyzers/availability")

    assert response.status_code == 200
    sarif = next(item for item in response.json() if item["analyzer"] == "sarif.import")
    assert sarif["status"] == "not_requested"


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
    assert any("workspace_id" in revision.read_text() for revision in revisions)


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


def test_quality_gate_configuration_is_forwarded_to_analysis_services() -> None:
    compose = (Path(__file__).parents[2] / "docker-compose.yml").read_text()

    for variable in (
        "QUALITY_GATE_MAX_NEW_CRITICAL_FINDINGS",
        "QUALITY_GATE_MAX_RISK_SCORE",
        "QUALITY_GATE_MAX_NEW_HOTSPOTS",
    ):
        assert compose.count(variable) >= 3
