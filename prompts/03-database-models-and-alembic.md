# CodePilot — OpenCode / Gentle AI

## Working mode

- Use **Sol** for architecture, analysis, trade-offs and implementation planning.
- Use **Luna** for implementation, tests, refactoring and documentation.
- Inspect the current repository before making changes.
- Preserve existing working code unless the prompt explicitly requires replacing it.
- Do not implement future phases prematurely.
- Prefer small, reviewable changes over broad rewrites.
- Do not push, publish, or create external resources.
- Do not add secrets or real API keys.
- Run all relevant checks before finishing.
- When a dependency or tool is unavailable, document the limitation and leave the repository in a consistent state.

## Required completion report

At the end, provide:

1. Summary of implemented changes.
2. Architectural decisions and trade-offs.
3. Files created or modified.
4. Commands executed.
5. Test, lint and type-check results.
6. Remaining risks or intentionally deferred work.

# Prompt 03 — Persistence model and Alembic

## Goal

Replace temporary in-memory state with a real async PostgreSQL persistence layer and first migrations.

## Core entities

Design the minimum useful model for:

### Repository

- UUID
- name
- provider
- clone URL
- default branch
- visibility
- created/updated timestamps

### Analysis

- UUID
- repository ID
- requested commit or branch
- resolved commit SHA
- status
- failure code and safe failure message
- started/completed timestamps
- analyzer version
- created timestamp

### Finding

- UUID
- analysis ID
- analyzer
- rule ID
- severity
- title
- description
- file path
- line and column where available
- structured evidence JSON
- remediation metadata JSON
- deterministic fingerprint

## Tasks

1. Implement async SQLAlchemy engine and session management.
2. Define ORM models and separate API/domain schemas where useful.
3. Introduce repository interfaces and SQLAlchemy implementations.
4. Configure Alembic for async SQLAlchemy.
5. Create the first migration.
6. Update API routes to persist repositories and analyses.
7. Add pagination to repository and analysis list endpoints.
8. Add uniqueness and indexing decisions explicitly.
9. Add database integration tests.
10. Add a development command or Make/PowerShell equivalent for migrations.

## Constraints

- Do not store provider access tokens yet.
- Do not store cloned source code in PostgreSQL.
- Avoid exposing ORM models directly through FastAPI.
- Timestamps must be timezone-aware UTC.
- Analysis status transitions must be validated.

## Acceptance criteria

- A clean PostgreSQL database can be created with `alembic upgrade head`.
- Repository and analysis records survive application restarts.
- Foreign keys and indexes exist.
- Invalid status transitions are rejected.
- API tests use an isolated test database or transaction strategy.
- Tests, Ruff and Mypy pass.
