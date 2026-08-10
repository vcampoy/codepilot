from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from celery.exceptions import Retry
from sqlalchemy.exc import IntegrityError, OperationalError

from codepilot.domain.analysis import (
    AnalysisFinding,
    AnalysisRecord,
    AnalysisResult,
    AnalysisStatus,
    AnalysisSummary,
    InvalidAnalysisTransitionError,
    SourceContext,
    SourceLine,
    fingerprint_finding,
)
from codepilot.repositories.analysis import InMemoryAnalysisRepository
from codepilot.services.analysis import (
    AnalysisEnqueueError,
    AnalysisExecutionError,
    AnalysisService,
    AnalysisStatePersistenceError,
    PermanentAnalysisError,
    TransientAnalysisError,
)
from codepilot.services.repository_ingestion import (
    RepositoryCleanupError,
    RepositoryCloneError,
    RepositorySnapshot,
)
from codepilot.worker.analysis_tasks import (
    create_analysis_task,
    create_stale_recovery_task,
)
from codepilot.worker.celery_app import create_celery_app


@dataclass
class FakeIngestion:
    snapshot: RepositorySnapshot
    calls: int = 0

    @asynccontextmanager
    async def ingest(self, _url: str) -> AsyncIterator[RepositorySnapshot]:
        self.calls += 1
        yield self.snapshot


@dataclass
class FakeAnalyzer:
    result: AnalysisResult | None = None
    error: Exception | None = None
    calls: int = 0

    async def analyze(self, _snapshot: RepositorySnapshot) -> AnalysisResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


@dataclass
class RecordingQueue:
    analysis_ids: list[UUID]

    def enqueue(self, analysis_id: UUID) -> None:
        self.analysis_ids.append(analysis_id)


@dataclass
class FailingQueue:
    analysis_id: UUID | None = None

    def enqueue(self, analysis_id: UUID) -> None:
        self.analysis_id = analysis_id
        raise RuntimeError("broker unavailable")


@dataclass
class ErrorIngestion:
    error: Exception

    @asynccontextmanager
    async def ingest(self, _url: str) -> AsyncIterator[RepositorySnapshot]:
        raise self.error
        yield make_snapshot()


@dataclass
class CleanupFailingIngestion:
    snapshot: RepositorySnapshot

    @asynccontextmanager
    async def ingest(self, _url: str) -> AsyncIterator[RepositorySnapshot]:
        yield self.snapshot
        raise RepositoryCleanupError("workspace cleanup failed")


def make_snapshot() -> RepositorySnapshot:
    return RepositorySnapshot(
        repository_path=Path("C:/isolated/repository"),
        commit_sha="a" * 40,
        default_branch="main",
        primary_languages=("Python",),
        file_count=4,
        source_size_bytes=1200,
    )


def make_finding(message: str = "Avoid unsafe call") -> AnalysisFinding:
    return AnalysisFinding(
        path="src/example.py",
        rule_id="security.no-unsafe-call",
        severity="high",
        message=message,
        start_line=8,
        end_line=8,
    )


def test_request_persists_queued_analysis_and_enqueues_only_id() -> None:
    async def run() -> tuple[AnalysisStatus, str, list[UUID], UUID]:
        repository = InMemoryAnalysisRepository()
        queue = RecordingQueue([])
        service = AnalysisService(repository, FakeIngestion(make_snapshot()), FakeAnalyzer(), queue)
        record = await service.request_analysis("https://github.com/example/project.git")
        return record.status, record.repository_url, queue.analysis_ids, record.analysis_id

    status, repository_url, analysis_ids, analysis_id = asyncio.run(run())

    assert status is AnalysisStatus.QUEUED
    assert repository_url.endswith("project.git")
    assert analysis_ids == [analysis_id]


def test_repository_enforces_analysis_state_transitions() -> None:
    async def run() -> None:
        repository = InMemoryAnalysisRepository()
        record = await repository.create("https://github.com/example/project.git")
        summary = AnalysisSummary(4, 30, {}, 0.1)

        with pytest.raises(InvalidAnalysisTransitionError):
            await repository.complete(record.analysis_id, AnalysisResult(4, 30, ()), summary)

        token = await repository.claim_running(record.analysis_id)
        assert token is not None
        running = await repository.get(record.analysis_id)
        assert running is not None
        assert running.status is AnalysisStatus.RUNNING

        await repository.complete(
            record.analysis_id,
            AnalysisResult(4, 30, ()),
            summary,
            lease_token=token,
        )

        with pytest.raises(InvalidAnalysisTransitionError):
            await repository.fail(record.analysis_id, "failed", retryable=False)

    asyncio.run(run())


def test_finding_persistence_is_idempotent_by_deterministic_fingerprint() -> None:
    async def run() -> tuple[AnalysisFinding, ...]:
        repository = InMemoryAnalysisRepository()
        record = await repository.create("https://github.com/example/project.git")
        token = await repository.claim_running(record.analysis_id)
        assert token is not None
        finding = make_finding()

        assert fingerprint_finding(finding) == fingerprint_finding(finding)
        assert (
            await repository.persist_findings(
                record.analysis_id, [finding, finding], lease_token=token
            )
            == 1
        )
        assert (
            await repository.persist_findings(record.analysis_id, [finding], lease_token=token) == 0
        )
        return await repository.get_findings(record.analysis_id)

    assert asyncio.run(run()) == (make_finding(),)


def test_expired_lease_cannot_mutate_findings_failure_or_completion() -> None:
    async def run() -> None:
        summary = AnalysisSummary(4, 30, {}, 0.1)

        async def claim() -> tuple[InMemoryAnalysisRepository, UUID, datetime]:
            repository = InMemoryAnalysisRepository()
            record = await repository.create("https://github.com/example/project.git")
            started = datetime(2026, 1, 1, tzinfo=UTC)
            token = await repository.claim_running(
                record.analysis_id, now=started, lease_seconds=10
            )
            assert token is not None
            return repository, token, started + timedelta(seconds=11)

        findings_repository, findings_token, expired_at = await claim()
        finding_record = await findings_repository.get(next(iter(findings_repository._records)))
        assert finding_record is not None
        with pytest.raises(InvalidAnalysisTransitionError):
            await findings_repository.persist_findings(
                finding_record.analysis_id,
                [make_finding()],
                lease_token=findings_token,
                now=expired_at,
            )

        requeue_repository, requeue_token, expired_at = await claim()
        requeue_record = await requeue_repository.get(next(iter(requeue_repository._records)))
        assert requeue_record is not None
        with pytest.raises(InvalidAnalysisTransitionError):
            await requeue_repository.requeue(
                requeue_record.analysis_id,
                lease_token=requeue_token,
                now=expired_at,
            )

        complete_repository, complete_token, expired_at = await claim()
        complete_record = await complete_repository.get(next(iter(complete_repository._records)))
        assert complete_record is not None
        with pytest.raises(InvalidAnalysisTransitionError):
            await complete_repository.complete(
                complete_record.analysis_id,
                AnalysisResult(4, 30, ()),
                summary,
                lease_token=complete_token,
                now=expired_at,
            )

        failure_repository, failure_token, expired_at = await claim()
        failure_record = await failure_repository.get(next(iter(failure_repository._records)))
        assert failure_record is not None
        with pytest.raises(InvalidAnalysisTransitionError):
            await failure_repository.fail(
                failure_record.analysis_id,
                "failed",
                retryable=False,
                lease_token=failure_token,
                now=expired_at,
            )

    asyncio.run(run())


def test_service_persists_summary_and_duplicate_delivery_does_not_repeat_work() -> None:
    async def run() -> tuple[AnalysisRecord | None, int, int]:
        repository = InMemoryAnalysisRepository()
        ingestion = FakeIngestion(make_snapshot())
        analyzer = FakeAnalyzer(AnalysisResult(4, 30, (make_finding(), make_finding())))
        service = AnalysisService(repository, ingestion, analyzer, RecordingQueue([]))
        record = await service.request_analysis("https://github.com/example/project.git")
        await service.process_analysis(record.analysis_id)
        await service.process_analysis(record.analysis_id)
        return await repository.get(record.analysis_id), ingestion.calls, analyzer.calls

    completed, ingestion_calls, analyzer_calls = asyncio.run(run())
    assert completed is not None
    assert completed.status is AnalysisStatus.COMPLETED
    assert completed.summary is not None
    assert completed.summary.analyzed_file_count == 4
    assert completed.summary.source_lines == 30
    assert completed.summary.finding_count_by_severity == {"high": 1}
    assert ingestion_calls == 1
    assert analyzer_calls == 1


def test_service_rejects_result_when_required_analyzers_did_not_execute() -> None:
    async def run() -> AnalysisRecord | None:
        repository = InMemoryAnalysisRepository()
        analyzer = FakeAnalyzer(AnalysisResult(4, 30, (), enforce_execution=True))
        service = AnalysisService(
            repository, FakeIngestion(make_snapshot()), analyzer, RecordingQueue([])
        )
        record = await service.request_analysis("https://github.com/example/project.git")
        with pytest.raises(PermanentAnalysisError, match="No required analyzer"):
            await service.process_analysis(record.analysis_id)
        return await repository.get(record.analysis_id)

    failed = asyncio.run(run())
    assert failed is not None
    assert failed.status is AnalysisStatus.FAILED
    assert failed.failure_message == "No compatible analyzer could execute."


def test_legacy_finding_is_upgraded_without_duplicate_on_new_analyzer_identity() -> None:
    async def run() -> tuple[int, tuple[AnalysisFinding, ...]]:
        repository = InMemoryAnalysisRepository()
        record = await repository.create("https://github.com/example/project.git")
        lease = await repository.claim_running(record.analysis_id)
        assert lease is not None
        legacy = AnalysisFinding(
            path="/workspace/repository/src/example.py",
            rule_id="security.no-unsafe-call",
            severity="high",
            message="Avoid unsafe call",
            start_line=8,
            end_line=8,
        )
        await repository.persist_findings(record.analysis_id, (legacy,), lease_token=lease)
        current = AnalysisFinding(
            path=legacy.path,
            rule_id=legacy.rule_id,
            severity=legacy.severity,
            message=legacy.message,
            start_line=legacy.start_line,
            end_line=legacy.end_line,
            analyzer="python.ruff",
            title="Unsafe call",
            evidence="Call expression",
            remediation="Use safe API",
            source_context=SourceContext(7, 9, (SourceLine(8, "unsafe()", True),)),
        )
        count = await repository.persist_findings(record.analysis_id, (current,), lease_token=lease)
        return count, await repository.get_findings(record.analysis_id)

    count, findings = asyncio.run(run())
    assert count == 1
    assert len(findings) == 1
    assert findings[0].analyzer == "python.ruff"
    assert findings[0].title == "Unsafe call"
    assert findings[0].evidence == "Call expression"
    assert findings[0].remediation == "Use safe API"
    assert findings[0].source_context is not None


def test_transient_failure_is_publicly_safe_and_requeued() -> None:
    async def run() -> AnalysisRecord | None:
        repository = InMemoryAnalysisRepository()
        analyzer = FakeAnalyzer(error=TransientAnalysisError("database connection reset"))
        service = AnalysisService(
            repository, FakeIngestion(make_snapshot()), analyzer, RecordingQueue([])
        )
        record = await service.request_analysis("https://github.com/example/project.git")
        with pytest.raises(TransientAnalysisError):
            await service.process_analysis(record.analysis_id)
        return await repository.get(record.analysis_id)

    failed = asyncio.run(run())
    assert failed is not None
    assert failed.status is AnalysisStatus.QUEUED
    assert failed.retryable is False
    assert failed.failure_message is None


def test_transient_failure_is_requeued_before_terminal_failure() -> None:
    async def run() -> tuple[AnalysisStatus, int]:
        repository = InMemoryAnalysisRepository()
        analyzer = FakeAnalyzer(error=TransientAnalysisError("temporary"))
        service = AnalysisService(
            repository, FakeIngestion(make_snapshot()), analyzer, RecordingQueue([])
        )
        record = await service.request_analysis("https://github.com/example/project.git")
        with pytest.raises(TransientAnalysisError):
            await service.process_analysis(record.analysis_id)
        failed = await repository.get(record.analysis_id)
        assert failed is not None
        return failed.status, analyzer.calls

    status, calls = asyncio.run(run())
    assert status is AnalysisStatus.QUEUED
    assert calls == 1


def test_clone_failure_is_terminal_and_not_retryable() -> None:
    async def run() -> tuple[AnalysisStatus, bool]:
        repository = InMemoryAnalysisRepository()
        service = AnalysisService(
            repository,
            ErrorIngestion(RepositoryCloneError("invalid repository")),
            FakeAnalyzer(AnalysisResult(0, 0, ())),
            RecordingQueue([]),
        )
        record = await service.request_analysis("https://github.com/example/project.git")
        with pytest.raises(PermanentAnalysisError):
            await service.process_analysis(record.analysis_id)
        failed = await repository.get(record.analysis_id)
        assert failed is not None
        return failed.status, failed.retryable

    status, retryable = asyncio.run(run())
    assert status is AnalysisStatus.FAILED
    assert retryable is False


def test_unexpected_analyzer_failure_is_terminal_and_not_retryable() -> None:
    async def run() -> tuple[AnalysisStatus, bool]:
        repository = InMemoryAnalysisRepository()
        service = AnalysisService(
            repository,
            FakeIngestion(make_snapshot()),
            FakeAnalyzer(error=RuntimeError("programming error")),
            RecordingQueue([]),
        )
        record = await service.request_analysis("https://github.com/example/project.git")
        with pytest.raises(PermanentAnalysisError):
            await service.process_analysis(record.analysis_id)
        failed = await repository.get(record.analysis_id)
        assert failed is not None
        return failed.status, failed.retryable

    status, retryable = asyncio.run(run())
    assert status is AnalysisStatus.FAILED
    assert retryable is False


def test_cleanup_failure_after_completion_preserves_completed_state() -> None:
    async def run() -> AnalysisStatus:
        repository = InMemoryAnalysisRepository()
        service = AnalysisService(
            repository,
            CleanupFailingIngestion(make_snapshot()),
            FakeAnalyzer(AnalysisResult(4, 30, ())),
            RecordingQueue([]),
        )
        record = await service.request_analysis("https://github.com/example/project.git")
        await service.process_analysis(record.analysis_id)
        completed = await repository.get(record.analysis_id)
        assert completed is not None
        return completed.status

    assert asyncio.run(run()) is AnalysisStatus.COMPLETED


def test_enqueue_failure_persists_terminal_safe_failure() -> None:
    async def run() -> tuple[AnalysisStatus, str | None]:
        repository = InMemoryAnalysisRepository()
        queue = FailingQueue()
        service = AnalysisService(repository, FakeIngestion(make_snapshot()), FakeAnalyzer(), queue)
        with pytest.raises(AnalysisEnqueueError):
            await service.request_analysis("https://github.com/example/project.git")
        assert queue.analysis_id is not None
        failed = await repository.get(queue.analysis_id)
        assert failed is not None
        return failed.status, failed.failure_message

    status, message = asyncio.run(run())
    assert status is AnalysisStatus.FAILED
    assert message == "Analysis could not be queued."


def test_enqueue_compensation_cannot_fail_a_competing_running_delivery() -> None:
    class PublishRaceRepository(InMemoryAnalysisRepository):
        rival_token: UUID | None = None

        async def fail(
            self,
            analysis_id: UUID,
            message: str,
            *,
            retryable: bool,
            lease_token: UUID | None = None,
            now: datetime | None = None,
        ) -> None:
            self.rival_token = await super().claim_running(analysis_id)
            await super().fail(
                analysis_id,
                message,
                retryable=retryable,
                lease_token=lease_token,
                now=now,
            )

        async def fail_queued(self, analysis_id: UUID, message: str) -> None:
            self.rival_token = await super().claim_running(analysis_id)
            await super().fail_queued(analysis_id, message)

    async def run() -> tuple[AnalysisStatus, UUID | None]:
        repository = PublishRaceRepository()
        service = AnalysisService(
            repository,
            FakeIngestion(make_snapshot()),
            FakeAnalyzer(),
            FailingQueue(),
        )
        with pytest.raises(AnalysisEnqueueError):
            await service.request_analysis("https://github.com/example/project.git")
        analysis_id = next(iter(repository._records))
        record = await repository.get(analysis_id)
        assert record is not None
        return record.status, repository.rival_token

    status, rival_token = asyncio.run(run())
    assert status is AnalysisStatus.RUNNING
    assert rival_token is not None


def test_operational_error_during_claim_is_transient() -> None:
    class DatabaseUnavailableRepository(InMemoryAnalysisRepository):
        async def recover_stale_running(self, *, now: datetime) -> int:
            return 0

        async def claim_running(
            self,
            analysis_id: UUID,
            *,
            now: datetime | None = None,
            lease_seconds: float = 900.0,
        ) -> UUID | None:
            raise OperationalError("UPDATE", {}, ConnectionError("database reset"))

    async def run() -> None:
        repository = DatabaseUnavailableRepository()
        service = AnalysisService(
            repository,
            FakeIngestion(make_snapshot()),
            FakeAnalyzer(),
            RecordingQueue([]),
        )
        record = await service.request_analysis("https://github.com/example/project.git")
        with pytest.raises(TransientAnalysisError):
            await service.process_analysis(record.analysis_id)

    asyncio.run(run())


def test_integrity_error_during_claim_is_not_transient() -> None:
    class InvalidDatabaseOperationRepository(InMemoryAnalysisRepository):
        async def recover_stale_running(self, *, now: datetime) -> int:
            raise IntegrityError("INSERT", {}, ValueError("constraint violation"))

    async def run() -> None:
        repository = InvalidDatabaseOperationRepository()
        service = AnalysisService(
            repository,
            FakeIngestion(make_snapshot()),
            FakeAnalyzer(),
            RecordingQueue([]),
        )
        record = await service.request_analysis("https://github.com/example/project.git")
        with pytest.raises(PermanentAnalysisError):
            await service.process_analysis(record.analysis_id)

    asyncio.run(run())


def test_periodic_recovery_retries_sqlalchemy_operational_error() -> None:
    class DatabaseFailureRepository(InMemoryAnalysisRepository):
        async def recover_stale_running(self, *, now: datetime) -> int:
            raise OperationalError("SELECT", {}, ConnectionError("database reset"))

    celery = create_celery_app()
    service = AnalysisService(
        DatabaseFailureRepository(),
        FakeIngestion(make_snapshot()),
        FakeAnalyzer(),
        RecordingQueue([]),
    )
    task = create_stale_recovery_task(celery, lambda: service)

    with pytest.raises(Retry):
        task.apply(throw=True)


def test_stale_running_analysis_is_reclaimed_atomically() -> None:
    async def run() -> tuple[bool, bool, AnalysisStatus]:
        repository = InMemoryAnalysisRepository()
        record = await repository.create("https://github.com/example/project.git")
        started = datetime(2026, 1, 1, tzinfo=UTC)

        first_claim = await repository.claim_running(
            record.analysis_id, now=started, lease_seconds=10
        )
        reclaimed = await repository.recover_stale_running(now=started + timedelta(seconds=11))
        second_claim = await repository.claim_running(
            record.analysis_id,
            now=started + timedelta(seconds=11),
            lease_seconds=10,
        )
        current = await repository.get(record.analysis_id)
        assert current is not None
        return (
            first_claim is not None,
            reclaimed == 1 and second_claim is not None,
            current.status,
        )

    first_claim, recovered, status = asyncio.run(run())
    assert first_claim is True
    assert recovered is True
    assert status is AnalysisStatus.RUNNING


def test_heartbeat_prevents_active_analysis_from_being_reclaimed() -> None:
    async def run() -> int:
        repository = InMemoryAnalysisRepository()
        record = await repository.create("https://github.com/example/project.git")
        started = datetime(2026, 1, 1, tzinfo=UTC)
        token = await repository.claim_running(record.analysis_id, now=started, lease_seconds=10)
        assert token is not None

        assert (
            await repository.heartbeat(
                record.analysis_id,
                now=started + timedelta(seconds=5),
                lease_seconds=10,
                lease_token=token,
            )
            is True
        )
        return await repository.recover_stale_running(now=started + timedelta(seconds=11))

    assert asyncio.run(run()) == 0


def test_reclaimed_lease_cannot_complete_the_previous_worker_attempt() -> None:
    async def run() -> None:
        repository = InMemoryAnalysisRepository()
        record = await repository.create("https://github.com/example/project.git")
        started = datetime(2026, 1, 1, tzinfo=UTC)
        old_lease = await repository.claim_running(
            record.analysis_id, now=started, lease_seconds=10
        )
        assert old_lease is not None
        await repository.recover_stale_running(now=started + timedelta(seconds=11))
        new_lease = await repository.claim_running(
            record.analysis_id,
            now=started + timedelta(seconds=11),
            lease_seconds=10,
        )
        assert new_lease is not None
        summary = AnalysisSummary(0, 0, {}, 0.1)

        with pytest.raises(InvalidAnalysisTransitionError):
            await repository.complete(
                record.analysis_id,
                AnalysisResult(0, 0, ()),
                summary,
                lease_token=old_lease,
            )

    asyncio.run(run())


def test_failure_state_persistence_error_is_explicitly_retryable() -> None:
    class FailingRequeueRepository(InMemoryAnalysisRepository):
        attempts = 0

        async def requeue(
            self,
            analysis_id: UUID,
            *,
            lease_token: UUID | None = None,
            now: datetime | None = None,
        ) -> None:
            self.attempts += 1
            if self.attempts == 1:
                raise ConnectionError("database connection reset")
            await super().requeue(analysis_id, lease_token=lease_token, now=now)

    async def run() -> tuple[AnalysisStatus, AnalysisStatus]:
        repository = FailingRequeueRepository()
        service = AnalysisService(
            repository,
            FakeIngestion(make_snapshot()),
            FakeAnalyzer(error=TransientAnalysisError("temporary")),
            RecordingQueue([]),
        )
        record = await service.request_analysis("https://github.com/example/project.git")

        with pytest.raises(AnalysisStatePersistenceError) as raised:
            await service.process_analysis(record.analysis_id)
        running = await repository.get(record.analysis_id)
        assert running is not None

        await service.recover_failure_state(record.analysis_id, raised.value)
        recovered = await repository.get(record.analysis_id)
        assert recovered is not None
        return running.status, recovered.status

    running, recovered = asyncio.run(run())
    assert running is AnalysisStatus.RUNNING
    assert recovered is AnalysisStatus.QUEUED


def test_failure_state_recovery_preserves_permanent_intent() -> None:
    class FailingFailRepository(InMemoryAnalysisRepository):
        attempts = 0

        async def fail(
            self,
            analysis_id: UUID,
            message: str,
            *,
            retryable: bool,
            lease_token: UUID | None = None,
            now: datetime | None = None,
        ) -> None:
            self.attempts += 1
            if self.attempts == 1:
                raise ConnectionError("database connection reset")
            await super().fail(
                analysis_id,
                message,
                retryable=retryable,
                lease_token=lease_token,
                now=now,
            )

    async def run() -> AnalysisRecord | None:
        repository = FailingFailRepository()
        service = AnalysisService(
            repository,
            FakeIngestion(make_snapshot()),
            FakeAnalyzer(error=PermanentAnalysisError("unsupported repository")),
            RecordingQueue([]),
        )
        record = await service.request_analysis("https://github.com/example/project.git")

        with pytest.raises(AnalysisStatePersistenceError) as raised:
            await service.process_analysis(record.analysis_id)

        await service.recover_failure_state(record.analysis_id, raised.value)
        return await repository.get(record.analysis_id)

    failed = asyncio.run(run())
    assert failed is not None
    assert failed.status is AnalysisStatus.FAILED
    assert failed.retryable is False


def test_celery_recovery_reconstructs_original_failure_classification() -> None:
    class RecoveryService:
        recovered_error: AnalysisExecutionError | None = None

        async def recover_failure_state(
            self,
            _analysis_id: UUID,
            error: AnalysisExecutionError,
            _lease_token: UUID | None = None,
            terminalize_retryable: bool = False,
        ) -> None:
            del terminalize_retryable
            self.recovered_error = error

        async def process_analysis(
            self, _analysis_id: UUID, *, terminalize_transient: bool = False
        ) -> None:
            del terminalize_transient

        async def close(self) -> None:
            pass

    celery = create_celery_app()
    service = RecoveryService()
    task = create_analysis_task(celery, lambda: cast(AnalysisService, service))

    result = task.apply(
        args=[str(uuid4()), True, None, False],
        throw=True,
    )

    assert result.successful()
    assert isinstance(service.recovered_error, PermanentAnalysisError)


def test_terminal_retry_failure_requires_current_lease_owner() -> None:
    class RacingRepository(InMemoryAnalysisRepository):
        rival_token: UUID | None = None
        terminal_failure_token: UUID | None = None

        async def requeue(
            self,
            analysis_id: UUID,
            *,
            lease_token: UUID | None = None,
            now: datetime | None = None,
        ) -> None:
            await super().requeue(analysis_id, lease_token=lease_token, now=now)
            self.rival_token = await super().claim_running(analysis_id)

        async def fail(
            self,
            analysis_id: UUID,
            message: str,
            *,
            retryable: bool,
            lease_token: UUID | None = None,
            now: datetime | None = None,
        ) -> None:
            self.terminal_failure_token = lease_token
            await super().fail(
                analysis_id,
                message,
                retryable=retryable,
                lease_token=lease_token,
                now=now,
            )

    repository = RacingRepository()
    service = AnalysisService(
        repository,
        FakeIngestion(make_snapshot()),
        FakeAnalyzer(error=TransientAnalysisError("temporary")),
        RecordingQueue([]),
    )

    async def create_record() -> UUID:
        record = await service.request_analysis("https://github.com/example/project.git")
        return record.analysis_id

    analysis_id = asyncio.run(create_record())
    celery = create_celery_app()
    celery.conf.task_always_eager = True
    task = create_analysis_task(celery, lambda: service)

    result = task.apply(args=[str(analysis_id)], retries=3, throw=True)
    assert result.successful()

    async def read_result() -> tuple[AnalysisStatus, UUID | None, UUID | None]:
        current = await repository.get(analysis_id)
        assert current is not None
        return current.status, repository.rival_token, repository.terminal_failure_token

    status, rival_token, terminal_token = asyncio.run(read_result())
    assert status is AnalysisStatus.FAILED
    assert rival_token is None
    assert terminal_token is not None


def test_periodic_recovery_task_reclaims_stale_work_and_closes_service() -> None:
    class RecoveryService:
        recovered = 0
        closed = False

        async def recover_stale_analyses(self) -> int:
            self.recovered += 1
            return 2

        async def close(self) -> None:
            self.closed = True

    celery = create_celery_app()
    celery.conf.task_always_eager = True
    service = RecoveryService()
    task = create_stale_recovery_task(celery, lambda: cast(AnalysisService, service))

    result = task.apply(throw=True)

    assert result.successful()
    assert result.result is None
    assert service.recovered == 1
    assert service.closed is True


def test_periodic_recovery_retries_queue_delivery_after_compensation_fails() -> None:
    class FailingCompensationRepository(InMemoryAnalysisRepository):
        async def fail_queued(self, analysis_id: UUID, message: str) -> None:
            raise ConnectionError("database unavailable")

    class RecoveringQueue:
        def __init__(self) -> None:
            self.analysis_ids: list[UUID] = []
            self.attempts = 0

        def enqueue(self, analysis_id: UUID) -> None:
            self.attempts += 1
            if self.attempts == 1:
                raise ConnectionError("broker unavailable")
            self.analysis_ids.append(analysis_id)

    async def run() -> tuple[AnalysisStatus, int, list[UUID]]:
        repository = FailingCompensationRepository()
        queue = RecoveringQueue()
        service = AnalysisService(
            repository,
            FakeIngestion(make_snapshot()),
            FakeAnalyzer(),
            queue,
            lease_seconds=10,
        )
        with pytest.raises(AnalysisEnqueueError):
            await service.request_analysis("https://github.com/example/project.git")

        record = next(iter(repository._records.values()))
        recovered = await service.recover_stale_analyses(
            now=record.created_at + timedelta(seconds=11)
        )
        current = await repository.get(record.analysis_id)
        assert current is not None
        return current.status, recovered, queue.analysis_ids

    status, recovered, analysis_ids = asyncio.run(run())
    assert status is AnalysisStatus.QUEUED
    assert recovered == 1
    assert len(analysis_ids) == 1


def test_permanent_failure_is_not_retryable_and_hides_internal_detail() -> None:
    async def run() -> AnalysisRecord | None:
        repository = InMemoryAnalysisRepository()
        analyzer = FakeAnalyzer(error=PermanentAnalysisError("invalid analyzer configuration"))
        service = AnalysisService(
            repository, FakeIngestion(make_snapshot()), analyzer, RecordingQueue([])
        )
        record = await service.request_analysis("https://github.com/example/project.git")
        with pytest.raises(PermanentAnalysisError):
            await service.process_analysis(record.analysis_id)
        return await repository.get(record.analysis_id)

    failed = asyncio.run(run())
    assert failed is not None
    assert failed.status is AnalysisStatus.FAILED
    assert failed.retryable is False
    assert failed.failure_message == "Analysis could not be completed."


def test_celery_task_runs_application_service_without_returning_product_payload() -> None:
    celery = create_celery_app()
    celery.conf.task_always_eager = True
    repository = InMemoryAnalysisRepository()
    queue = RecordingQueue([])
    service = AnalysisService(
        repository,
        FakeIngestion(make_snapshot()),
        FakeAnalyzer(AnalysisResult(4, 30, ())),
        queue,
    )

    async def create_record() -> UUID:
        return (
            await service.request_analysis("https://github.com/example/project.git")
        ).analysis_id

    analysis_id = asyncio.run(create_record())
    task = create_analysis_task(celery, lambda: service)

    result = task.apply(args=[str(analysis_id)], throw=True)

    assert result.successful()
    assert result.result is None


def test_celery_task_retries_transient_failures() -> None:
    celery = create_celery_app()
    celery.conf.task_always_eager = True
    repository = InMemoryAnalysisRepository()
    service = AnalysisService(
        repository,
        FakeIngestion(make_snapshot()),
        FakeAnalyzer(error=TransientAnalysisError("temporary")),
        RecordingQueue([]),
    )

    async def create_record() -> UUID:
        return (
            await service.request_analysis("https://github.com/example/project.git")
        ).analysis_id

    analysis_id = asyncio.run(create_record())
    task = create_analysis_task(celery, lambda: service)

    celery.conf.task_always_eager = True
    with pytest.raises(Retry):
        task.apply(args=[str(analysis_id)], throw=True)
