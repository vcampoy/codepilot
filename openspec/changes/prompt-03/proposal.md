# Proposal: Async Persistence Model and Alembic Foundation

## Intent

Establish PostgreSQL storage for repositories, analyses, and findings, plus repository/analysis create-list APIs.

## Scope

### In Scope
- Async engine/session/unit-of-work lifecycle, typed mappings, and an async Alembic revision.
- Domain transitions: `queued -> running -> completed|failed` and `queued -> failed`.
- UUID/UTC models; unique repository `(provider,clone_url)` and finding `(analysis_id,fingerprint)`; indexed foreign keys, query indexes, and cascades.
- Repository and nested-analysis create/list services and routes; stable `created_at, id` pagination using `{items,total,offset,limit}` and `limit <= 100`.
- PostgreSQL tests/CI, migration command, and documentation.

### Out of Scope
- Prompt 04 URL security/canonicalization, cloning, inspection, and resolved SHA.
- Prompt 05 Celery enqueue/orchestration, worker transitions, retries, summaries, and status endpoint semantics; analysis creation only persists `queued` and returns `201`.
- Public finding routes, delete APIs, provider tokens, source storage, authentication, or AI behavior.

## Capabilities

### New Capabilities
- `persistence-layer`: Async lifecycle, domain invariants, mappings, contracts, migrations, constraints, and isolation.
- `repository-analysis-api`: Repository/nested-analysis create-list behavior, pagination, and errors.

### Modified Capabilities
None.

## Approach

Preserve `api -> services -> repository contracts <- SQLAlchemy adapters -> db`. One `AsyncSession` serves each request/task; the unit of work controls commit/rollback, dependencies close it, and lifespan disposes the engine. Adapter-private ORM maps to domain types. Alembic uses the runtime secret URL, normalizing `postgresql://` to `postgresql+asyncpg://`.

Repository create accepts `name,provider,clone_url,default_branch,visibility`; analysis create accepts `requested_ref`, persists `queued`, and returns `201`. Enums are provider `github|gitlab|bitbucket|other`, visibility `public|private`, status `queued|running|completed|failed`, and severity `info|low|medium|high|critical`. Separate Pydantic schemas preserve duplicate `409` and missing-parent `404` errors.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `backend/src/codepilot/{db,domain,repositories,services}/` | New | Layers and use cases |
| `backend/src/codepilot/api/v1/`, `main.py` | Modified | Routes and wiring |
| `backend/migrations/`, tests, CI, docs | New/Modified | Schema, verification, commands |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Commits escape test rollback | Medium | Savepoint-compatible sessions or disposable schemas |
| ORM and migration drift | Medium | CI upgrades a clean PostgreSQL database to `head` |
| Review exceeds 400 lines | High | Resolve ask-always delivery choice before APPLY; prefer three slices |

## Rollback Plan

Stop writes, downgrade to `base`, and revert wiring/routes to the discovery-only API. No legacy migration is required.

## Dependencies

- Existing dependencies, Compose PostgreSQL, typed `DATABASE_URL`, and Python 3.13.
- APPLY must use `openai/gpt-5.6-luna`, variant `high`, after the chained-PR decision.

## Success Criteria

- [ ] Clean PostgreSQL passes upgrade, downgrade, and re-upgrade; required constraints/indexes are verified.
- [ ] Records survive API restart; pagination is bounded/stable; duplicate, missing-parent, and invalid-transition cases are tested.
- [ ] Isolated PostgreSQL tests, Ruff lint/format, and strict Mypy pass in CI.
