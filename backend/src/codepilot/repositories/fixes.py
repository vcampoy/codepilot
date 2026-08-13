"""Persistence adapters for Fix Findings configuration and jobs."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import UUID

from sqlalchemy import JSON, Column, DateTime, MetaData, String, Table, Text, Uuid, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from codepilot.domain.fixes import FixConfiguration, FixJob, FixJobStatus


class FixRepository(Protocol):
    async def get_configuration(self, workspace_id: str) -> FixConfiguration: ...
    async def save_configuration(self, configuration: FixConfiguration) -> FixConfiguration: ...
    async def create_job(self, job: FixJob) -> FixJob: ...
    async def get_job(self, job_id: UUID, workspace_id: str | None = None) -> FixJob | None: ...
    async def update_job(
        self,
        job_id: UUID,
        *,
        status: FixJobStatus,
        workspace_id: str,
        error_message: str | None = None,
        pull_request_url: str | None = None,
    ) -> FixJob | None: ...


class InMemoryFixRepository:
    def __init__(self) -> None:
        self._configurations: dict[str, FixConfiguration] = {}
        self._jobs: dict[UUID, FixJob] = {}
        self._lock = asyncio.Lock()

    async def get_configuration(self, workspace_id: str) -> FixConfiguration:
        async with self._lock:
            return self._configurations.get(workspace_id, FixConfiguration(workspace_id))

    async def save_configuration(self, configuration: FixConfiguration) -> FixConfiguration:
        async with self._lock:
            self._configurations[configuration.workspace_id] = configuration
            return configuration

    async def create_job(self, job: FixJob) -> FixJob:
        async with self._lock:
            self._jobs[job.job_id] = replace(job)
            return replace(job)

    async def get_job(self, job_id: UUID, workspace_id: str | None = None) -> FixJob | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None or (workspace_id is not None and job.workspace_id != workspace_id):
                return None
            return replace(job)

    async def update_job(
        self,
        job_id: UUID,
        *,
        status: FixJobStatus,
        workspace_id: str,
        error_message: str | None = None,
        pull_request_url: str | None = None,
    ) -> FixJob | None:
        async with self._lock:
            current = self._jobs.get(job_id)
            if current is None or current.workspace_id != workspace_id:
                return None
            updated = replace(
                current,
                status=status,
                error_message=error_message,
                pull_request_url=pull_request_url,
                updated_at=datetime.now(UTC),
            )
            self._jobs[job_id] = updated
            return replace(updated)


_METADATA = MetaData()
_FIX_CONFIGURATIONS = Table(
    "codepilot_fix_configurations",
    _METADATA,
    Column("workspace_id", String(64), primary_key=True),
    Column("rules", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
_FIX_JOBS = Table(
    "codepilot_fix_jobs",
    _METADATA,
    Column("job_id", Uuid(as_uuid=True), primary_key=True),
    Column("analysis_id", Uuid(as_uuid=True), nullable=False),
    Column("workspace_id", String(64), nullable=False),
    Column("finding_ids", JSON, nullable=False),
    Column("status", String(16), nullable=False),
    Column("branch_name", String(128)),
    Column("pull_request_url", String(2048)),
    Column("error_message", String(512)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


class PostgresFixRepository:
    def __init__(self, database_url: str, engine: AsyncEngine | None = None) -> None:
        self._engine = engine or create_async_engine(database_url, pool_pre_ping=True)

    async def get_configuration(self, workspace_id: str) -> FixConfiguration:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(_FIX_CONFIGURATIONS).where(
                            _FIX_CONFIGURATIONS.c.workspace_id == workspace_id
                        )
                    )
                )
                .mappings()
                .first()
            )
        return _configuration_from_row(row) if row else FixConfiguration(workspace_id)

    async def save_configuration(self, configuration: FixConfiguration) -> FixConfiguration:
        async with self._engine.begin() as connection:
            statement = postgresql_insert(_FIX_CONFIGURATIONS).values(
                _configuration_values(configuration)
            )
            statement = statement.on_conflict_do_update(
                index_elements=[_FIX_CONFIGURATIONS.c.workspace_id],
                set_={"rules": configuration.rules, "updated_at": configuration.updated_at},
            )
            await connection.execute(statement)
        return configuration

    async def create_job(self, job: FixJob) -> FixJob:
        async with self._engine.begin() as connection:
            await connection.execute(_FIX_JOBS.insert().values(_job_values(job)))
        return job

    async def get_job(self, job_id: UUID, workspace_id: str | None = None) -> FixJob | None:
        async with self._engine.connect() as connection:
            query = select(_FIX_JOBS).where(_FIX_JOBS.c.job_id == job_id)
            if workspace_id is not None:
                query = query.where(_FIX_JOBS.c.workspace_id == workspace_id)
            row = (await connection.execute(query)).mappings().first()
        return _job_from_row(row) if row else None

    async def update_job(
        self,
        job_id: UUID,
        *,
        status: FixJobStatus,
        workspace_id: str,
        error_message: str | None = None,
        pull_request_url: str | None = None,
    ) -> FixJob | None:
        now = datetime.now(UTC)
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(_FIX_JOBS)
                .where(_FIX_JOBS.c.job_id == job_id, _FIX_JOBS.c.workspace_id == workspace_id)
                .values(
                    status=status.value,
                    error_message=error_message,
                    pull_request_url=pull_request_url,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                return None
        return await self.get_job(job_id, workspace_id)

    async def dispose(self) -> None:
        await self._engine.dispose()


def _configuration_values(value: FixConfiguration) -> dict[str, object]:
    return {
        "workspace_id": value.workspace_id,
        "rules": value.rules,
        "updated_at": value.updated_at,
    }


def _job_values(value: FixJob) -> dict[str, object]:
    return {
        "job_id": value.job_id,
        "analysis_id": value.analysis_id,
        "workspace_id": value.workspace_id,
        "finding_ids": list(value.finding_ids),
        "status": value.status.value,
        "branch_name": value.branch_name,
        "pull_request_url": value.pull_request_url,
        "error_message": value.error_message,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
    }


def _configuration_from_row(row: Any) -> FixConfiguration:
    return FixConfiguration(
        str(row["workspace_id"]), str(row["rules"]), cast(datetime, row["updated_at"])
    )


def _job_from_row(row: Any) -> FixJob:
    return FixJob(
        job_id=cast(UUID, row["job_id"]),
        analysis_id=cast(UUID, row["analysis_id"]),
        workspace_id=str(row["workspace_id"]),
        finding_ids=tuple(str(x) for x in (row.get("finding_ids") or [])),
        status=FixJobStatus(str(row["status"])),
        branch_name=cast(str | None, row.get("branch_name")),
        pull_request_url=cast(str | None, row.get("pull_request_url")),
        error_message=cast(str | None, row.get("error_message")),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
    )
