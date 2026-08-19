import asyncio
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from codepilot.domain.analysis import (
    AnalysisFinding,
    AnalysisRecord,
    AnalysisStatus,
    fingerprint_finding,
)
from codepilot.domain.fixes import FixConfiguration, FixJobStatus
from codepilot.domain.llm_config import LlmConfiguration
from codepilot.main import create_app
from codepilot.repositories.analysis import InMemoryAnalysisRepository
from codepilot.repositories.fixes import InMemoryFixRepository
from codepilot.services.analysis import AnalysisService, NoopAnalyzer
from codepilot.services.fixes import FixService, FixValidationError
from codepilot.services.repository_ingestion import RepositorySnapshot


class Queue:
    def __init__(self) -> None:
        self.ids: list[UUID] = []

    def enqueue(self, job_id: UUID) -> None:
        self.ids.append(job_id)


def completed_with_finding() -> tuple[InMemoryAnalysisRepository, AnalysisRecord, AnalysisFinding]:
    async def scenario() -> tuple[InMemoryAnalysisRepository, AnalysisRecord, AnalysisFinding]:
        repo = InMemoryAnalysisRepository()
        record = await repo.create("https://github.com/acme/repo", "default")
        record.status = AnalysisStatus.COMPLETED
        record.commit_sha = "a" * 40
        repo._records[record.analysis_id] = record
        finding = AnalysisFinding("a.py", "R1", "high", "msg", 1, 1)
        repo._findings[record.analysis_id][fingerprint_finding(finding)] = finding
        await repo.save_llm_configuration(
            LlmConfiguration("default", True, "openai", "m", "secret", datetime.now(UTC))
        )
        return repo, record, finding

    return asyncio.run(scenario())


def test_create_fix_job_requires_enabled_llm_and_stable_finding_ids() -> None:
    async def scenario() -> None:
        repo = InMemoryAnalysisRepository()
        record = await repo.create("https://github.com/acme/repo", "default")
        record.status = AnalysisStatus.COMPLETED
        record.commit_sha = "a" * 40
        repo._records[record.analysis_id] = record
        finding = AnalysisFinding("a.py", "R1", "high", "msg", 1, 1)
        repo._findings[record.analysis_id][fingerprint_finding(finding)] = finding
        service = FixService(repo, InMemoryFixRepository(), Queue())
        with pytest.raises(FixValidationError, match="LLM enrichment"):
            await service.create_job(record.analysis_id, (fingerprint_finding(finding),), "default")

    asyncio.run(scenario())


def test_create_fix_job_persists_queued_job_and_branch() -> None:
    repo, record, finding = completed_with_finding()

    async def scenario() -> None:
        queue = Queue()
        service = FixService(
            repo,
            InMemoryFixRepository(),
            queue,
            now=lambda: datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )
        job = await service.create_job(
            record.analysis_id, (fingerprint_finding(finding),), "default"
        )
        assert job.status is FixJobStatus.QUEUED
        assert job.branch_name is not None
        assert job.branch_name.startswith("fix-findings-2026-01-02-03-04-05-")
        assert queue.ids == [job.job_id]

    asyncio.run(scenario())


def test_create_fix_job_rejects_duplicate_finding_ids() -> None:
    repo, record, finding = completed_with_finding()

    async def scenario() -> None:
        service = FixService(repo, InMemoryFixRepository(), Queue())
        finding_id = fingerprint_finding(finding)
        with pytest.raises(FixValidationError, match="unique"):
            await service.create_job(record.analysis_id, (finding_id, finding_id), "default")

    asyncio.run(scenario())


class ApiQueue:
    def enqueue(self, _id: UUID) -> None:
        pass


class ApiIngestion:
    def ingest(self, _url: str) -> AbstractAsyncContextManager[RepositorySnapshot]:
        raise AssertionError("ingestion must not run while testing fix settings")


def test_fix_rules_settings_round_trip() -> None:
    repo = InMemoryAnalysisRepository()
    analysis = AnalysisService(repo, ApiIngestion(), NoopAnalyzer(), ApiQueue())
    fix = FixService(repo, InMemoryFixRepository(), ApiQueue())
    with TestClient(create_app(analysis_service=analysis, fix_service=fix)) as client:
        saved = client.put(
            "/api/v1/settings/fixes",
            json={"rules": "Use strict TDD.", "max_findings_per_fix": 7},
        )
        loaded = client.get("/api/v1/settings/fixes")
    assert saved.status_code == 200
    assert loaded.json()["rules"] == "Use strict TDD."
    assert loaded.json()["max_findings_per_fix"] == 7


def test_fix_configuration_defaults_to_ten_findings_and_persists_limit() -> None:
    async def scenario() -> None:
        analysis_repository = InMemoryAnalysisRepository()
        repository = InMemoryFixRepository()
        service = FixService(analysis_repository, repository, ApiQueue())
        configuration = await service.save_configuration(
            "default", finding_rules="Rules", hotspot_rules="Hotspots", max_findings_per_fix=7
        )
        assert configuration.max_findings_per_fix == 7
        assert (await service.get_rules("default")).max_findings_per_fix == 7

    asyncio.run(scenario())


def test_fix_configuration_rejects_limit_outside_one_to_ten() -> None:
    async def scenario() -> None:
        service = FixService(InMemoryAnalysisRepository(), InMemoryFixRepository(), ApiQueue())
        with pytest.raises(FixValidationError, match="between 1 and 10"):
            await service.save_configuration(
                "default", finding_rules="", hotspot_rules="", max_findings_per_fix=11
            )

    asyncio.run(scenario())


def test_finding_job_uses_configured_limit_and_unique_branch_suffix() -> None:
    repo, record, finding = completed_with_finding()

    async def scenario() -> None:
        fix_repository = InMemoryFixRepository()
        await fix_repository.save_configuration(FixConfiguration("default", max_findings_per_fix=1))
        queue = Queue()
        service = FixService(
            repo,
            fix_repository,
            queue,
            now=lambda: datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )
        job = await service.create_job(
            record.analysis_id, (fingerprint_finding(finding),), "default"
        )
        assert job.branch_name is not None
        assert job.branch_name.startswith("fix-findings-2026-01-02-03-04-05-")

    asyncio.run(scenario())
