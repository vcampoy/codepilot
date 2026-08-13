import asyncio
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from codepilot.domain.analysis import AnalysisFinding, AnalysisStatus, fingerprint_finding
from codepilot.domain.fixes import FixJobStatus
from codepilot.domain.llm_config import LlmConfiguration
from codepilot.main import create_app
from codepilot.repositories.analysis import InMemoryAnalysisRepository
from codepilot.repositories.fixes import InMemoryFixRepository
from codepilot.services.analysis import AnalysisService
from codepilot.services.fixes import FixService, FixValidationError


class Queue:
    def __init__(self):
        self.ids = []

    def enqueue(self, job_id):
        self.ids.append(job_id)


def completed_with_finding():
    async def scenario():
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


def test_create_fix_job_requires_enabled_llm_and_stable_finding_ids():
    async def scenario():
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


def test_create_fix_job_persists_queued_job_and_branch():
    repo, record, finding = completed_with_finding()

    async def scenario():
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
        assert job.branch_name == "fix-findings-2026-01-02-03-04-05"
        assert queue.ids == [job.job_id]

    asyncio.run(scenario())


def test_create_fix_job_rejects_duplicate_finding_ids():
    repo, record, finding = completed_with_finding()

    async def scenario():
        service = FixService(repo, InMemoryFixRepository(), Queue())
        finding_id = fingerprint_finding(finding)
        with pytest.raises(FixValidationError, match="unique"):
            await service.create_job(record.analysis_id, (finding_id, finding_id), "default")

    asyncio.run(scenario())


class ApiQueue:
    def enqueue(self, _id):
        pass


def test_fix_rules_settings_round_trip():
    repo = InMemoryAnalysisRepository()
    analysis = AnalysisService(repo, object(), object(), ApiQueue())
    fix = FixService(repo, InMemoryFixRepository(), ApiQueue())
    with TestClient(create_app(analysis_service=analysis, fix_service=fix)) as client:
        saved = client.put("/api/v1/settings/fixes", json={"rules": "Use strict TDD."})
        loaded = client.get("/api/v1/settings/fixes")
    assert saved.status_code == 200
    assert loaded.json()["rules"] == "Use strict TDD."
