import asyncio
from datetime import UTC, datetime

import pytest

from codepilot.domain.analysis import AnalysisFinding, AnalysisStatus, fingerprint_finding
from codepilot.domain.fixes import FixJobStatus, FixTargetType
from codepilot.domain.insights import FileInsight
from codepilot.domain.llm_config import LlmConfiguration
from codepilot.repositories.analysis import InMemoryAnalysisRepository
from codepilot.repositories.fixes import InMemoryFixRepository
from codepilot.services.fix_runner import FixJobRunner
from codepilot.services.fixes import FixService
from codepilot.services.repair import RepairExecutionError, RepairExecutor, RepairResponse


class Queue:
    def enqueue(self, _job_id: object) -> None:
        return None


class Gateway:
    async def generate_repair(self, _request: object) -> RepairResponse:
        return RepairResponse(
            patch="diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
            title="Repair finding",
            description="Repair selected finding",
        )


class Sandbox:
    async def verify(self, _repository_url: str, _commit_sha: str, _patch: str) -> tuple[str, ...]:
        return ("pytest",)


class Publisher:
    def __init__(self) -> None:
        self.calls = 0

    async def publish(self, *_args: object) -> str:
        self.calls += 1
        return "https://github.com/acme/repo/pull/1"


def test_runner_claims_job_and_publishes_once() -> None:
    async def scenario() -> None:
        analysis_repository = InMemoryAnalysisRepository()
        analysis = await analysis_repository.create("https://github.com/acme/repo", "default")
        analysis.status = AnalysisStatus.COMPLETED
        analysis.commit_sha = "a" * 40
        analysis_repository._records[analysis.analysis_id] = analysis
        finding = AnalysisFinding("a.py", "R1", "high", "message", 1, 1)
        finding_id = fingerprint_finding(finding)
        analysis_repository._findings[analysis.analysis_id][finding_id] = finding
        await analysis_repository.save_llm_configuration(
            LlmConfiguration("default", True, "openai", "m", "secret", datetime.now(UTC))
        )
        fix_repository = InMemoryFixRepository()
        service = FixService(analysis_repository, fix_repository, Queue())
        job = await service.create_job(analysis.analysis_id, (finding_id,), "default")
        publisher = Publisher()
        runner = FixJobRunner(
            analysis_repository,
            fix_repository,
            RepairExecutor(Gateway(), Sandbox(), publisher),
        )

        await runner.run(job.job_id)
        await runner.run(job.job_id)
        result = await fix_repository.get_job(job.job_id)
        assert result is not None
        assert result.status is FixJobStatus.SUCCEEDED
        assert result.pull_request_url == "https://github.com/acme/repo/pull/1"
        assert publisher.calls == 1

    asyncio.run(scenario())


def test_runner_marks_failed_without_publishing_when_verification_fails() -> None:
    async def scenario() -> None:
        analysis_repository = InMemoryAnalysisRepository()
        analysis = await analysis_repository.create("https://github.com/acme/repo", "default")
        analysis.status = AnalysisStatus.COMPLETED
        analysis.commit_sha = "a" * 40
        analysis_repository._records[analysis.analysis_id] = analysis
        finding = AnalysisFinding("a.py", "R1", "high", "message", 1, 1)
        finding_id = fingerprint_finding(finding)
        analysis_repository._findings[analysis.analysis_id][finding_id] = finding
        await analysis_repository.save_llm_configuration(
            LlmConfiguration("default", True, "openai", "m", "secret", datetime.now(UTC))
        )
        fix_repository = InMemoryFixRepository()
        job = await FixService(analysis_repository, fix_repository, Queue()).create_job(
            analysis.analysis_id, (finding_id,), "default"
        )

        class FailingGateway(Gateway):
            async def generate_repair(self, _request: object) -> RepairResponse:
                raise RepairExecutionError("provider unavailable")

        publisher = Publisher()
        runner = FixJobRunner(
            analysis_repository,
            fix_repository,
            RepairExecutor(FailingGateway(), Sandbox(), publisher),
        )
        await runner.run(job.job_id)
        result = await fix_repository.get_job(job.job_id)
        assert result is not None
        assert result.status is FixJobStatus.FAILED
        assert result.pull_request_url is None
        assert publisher.calls == 0

    asyncio.run(scenario())


def test_runner_does_not_persist_provider_secrets_in_failure_message() -> None:
    async def scenario() -> None:
        analysis_repository = InMemoryAnalysisRepository()
        analysis = await analysis_repository.create("https://github.com/acme/repo", "default")
        analysis.status = AnalysisStatus.COMPLETED
        analysis.commit_sha = "a" * 40
        analysis_repository._records[analysis.analysis_id] = analysis
        finding = AnalysisFinding("a.py", "R1", "high", "message", 1, 1)
        finding_id = fingerprint_finding(finding)
        analysis_repository._findings[analysis.analysis_id][finding_id] = finding
        await analysis_repository.save_llm_configuration(
            LlmConfiguration("default", True, "openai", "m", "secret", datetime.now(UTC))
        )
        fix_repository = InMemoryFixRepository()
        job = await FixService(analysis_repository, fix_repository, Queue()).create_job(
            analysis.analysis_id, (finding_id,), "default"
        )

        class LeakingGateway(Gateway):
            async def generate_repair(self, _request: object) -> RepairResponse:
                raise RuntimeError("api_key=super-secret")

        runner = FixJobRunner(
            analysis_repository,
            fix_repository,
            RepairExecutor(LeakingGateway(), Sandbox(), Publisher()),
        )
        await runner.run(job.job_id)
        result = await fix_repository.get_job(job.job_id)
        assert result is not None
        assert result.status is FixJobStatus.FAILED
        assert result.error_message == "Fix execution failed."
        assert "super-secret" not in (result.error_message or "")

    asyncio.run(scenario())


def test_runner_redacts_natural_language_api_key_errors() -> None:
    async def scenario() -> None:
        analysis_repository = InMemoryAnalysisRepository()
        analysis = await analysis_repository.create("https://github.com/acme/repo", "default")
        analysis.status = AnalysisStatus.COMPLETED
        analysis.commit_sha = "a" * 40
        analysis_repository._records[analysis.analysis_id] = analysis
        finding = AnalysisFinding("a.py", "R1", "high", "message", 1, 1)
        finding_id = fingerprint_finding(finding)
        analysis_repository._findings[analysis.analysis_id][finding_id] = finding
        await analysis_repository.save_llm_configuration(
            LlmConfiguration("default", True, "openai", "m", "secret", datetime.now(UTC))
        )
        fix_repository = InMemoryFixRepository()
        job = await FixService(analysis_repository, fix_repository, Queue()).create_job(
            analysis.analysis_id, (finding_id,), "default"
        )

        class LeakingGateway(Gateway):
            async def generate_repair(self, _request: object) -> RepairResponse:
                raise RuntimeError("Incorrect API key provided: sk-proj-secret")

        runner = FixJobRunner(
            analysis_repository,
            fix_repository,
            RepairExecutor(LeakingGateway(), Sandbox(), Publisher()),
        )
        await runner.run(job.job_id)
        result = await fix_repository.get_job(job.job_id)
        assert result is not None
        assert result.error_message == "Fix execution failed."
        assert "sk-proj-secret" not in (result.error_message or "")

    asyncio.run(scenario())


def test_runner_builds_and_validates_hotspot_evidence() -> None:
    async def scenario() -> None:
        analysis_repository = InMemoryAnalysisRepository()
        analysis = await analysis_repository.create("https://github.com/acme/repo", "default")
        lease_token = await analysis_repository.claim_running(analysis.analysis_id)
        await analysis_repository.persist_file_insights(
            analysis.analysis_id,
            (FileInsight("src/main.py", 0.8, None, {}),),
            lease_token=lease_token,
        )
        runner = FixJobRunner(
            analysis_repository,
            InMemoryFixRepository(),
            RepairExecutor(Gateway(), Sandbox(), Publisher()),
        )

        evidence = await runner._evidence(
            FixTargetType.HOTSPOT, ("src/main.py",), analysis.analysis_id
        )
        assert evidence == ({"path": "src/main.py", "hotspot_score": 0.8},)
        with pytest.raises(RepairExecutionError, match="selected hotspots"):
            await runner._evidence(FixTargetType.HOTSPOT, ("missing.py",), analysis.analysis_id)
        with pytest.raises(RepairExecutionError, match="selected findings"):
            await runner._evidence(
                FixTargetType.FINDING, ("missing-finding",), analysis.analysis_id
            )

    asyncio.run(scenario())
