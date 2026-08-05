## Exploration: Prompt 03 — Persistence model and Alembic

### Current State
The authoritative request is `prompts/03-database-models-and-alembic.md`. Despite its
wording about replacing temporary state, the repository currently has no in-memory
repository, analysis, or finding implementation to replace: `db`, `domain`,
`repositories`, and `services` are package placeholders, and the v1 API only exposes
discovery metadata. Prompt 03 is therefore a greenfield persistence slice.

The required dependencies (SQLAlchemy async, asyncpg, and Alembic), typed
`DATABASE_URL`, PostgreSQL Compose service, stable error handling, and application
factory already exist. Missing pieces are engine/session ownership, domain and ORM
models, repository adapters, use-case services, product routes, migrations, pagination,
and database-test isolation. CI currently starts no PostgreSQL service. The local host is
Python 3.12 without pytest while the project requires Python 3.13; Docker is available.

Planning MUST preserve the documented dependency direction
`api -> services -> repository contracts <- SQLAlchemy adapters -> db`. Later APPLY
execution is constrained to `openai/gpt-5.6-luna` with variant `high`; this exploration
does not implement product code.

### Affected Areas
- `backend/src/codepilot/db/` and `backend/migrations/` — async engine/session plumbing,
  typed ORM metadata, Alembic async environment, and initial schema revision.
- `backend/src/codepilot/domain/` — persistence-independent entities, enums, and validated
  analysis status transitions.
- `backend/src/codepilot/repositories/` and `backend/src/codepilot/services/` — repository
  contracts, SQLAlchemy adapters, transaction boundary, and create/list use cases.
- `backend/src/codepilot/api/v1/` and `backend/src/codepilot/main.py` — separate Pydantic
  transport schemas, bounded pagination, dependency wiring, and engine disposal.
- `backend/tests/` and `.github/workflows/ci.yml` — unit tests plus isolated PostgreSQL
  migration/repository/API integration tests and a CI database service.
- `backend/pyproject.toml`, `README.md`, and `docs/architecture.md` — test tooling,
  migration commands, API behavior, and updated persistence status.

### Approaches
1. **Layered services with a SQLAlchemy unit of work** — keep ORM models private to the
   adapter; expose domain records and repository/unit-of-work protocols to services;
   inject one async unit of work per request.
   - Pros: Preserves the established dependency rule, makes commit/rollback ownership
     explicit, supports atomic status transitions, and gives later worker orchestration a
     stable persistence seam.
   - Cons: Adds more contracts and mapping code than direct CRUD and increases the review
     surface.
   - Effort: High

2. **Route-centric SQLAlchemy CRUD** — inject `AsyncSession` directly into FastAPI routes
   and return Pydantic projections from ORM operations.
   - Pros: Fewer files and faster initial delivery.
   - Cons: Violates the documented `api -> services` boundary, couples API tests to ORM
     details, obscures transaction ownership, and creates rework for Prompt 05 workers.
   - Effort: Medium

### Recommendation
Use the layered unit-of-work approach, but keep it narrow: repository, analysis, and
finding contracts only; create/list services only; no generic CRUD framework. One
`AsyncSession` belongs to one request/task, and the unit of work owns commit/rollback.
FastAPI dependencies create and close it; application lifespan disposes the engine.

Use SQLAlchemy 2 typed mappings with PostgreSQL UUID, JSONB, and timezone-aware
`TIMESTAMP WITH TIME ZONE`. Keep ORM classes out of API and domain contracts. Inject the
secret runtime database URL into Alembic's async `env.py` rather than storing credentials
in `alembic.ini`; normalize the already accepted `postgresql://` form to
`postgresql+asyncpg://` at the database boundary.

Apply these minimum schema decisions:

| Area | Decision |
| --- | --- |
| Repository identity | UUID primary key; exact unique `(provider, clone_url)`; name is not unique; defer URL canonicalization to Prompt 04. |
| Analysis lifecycle | `queued -> running -> completed|failed`, plus `queued -> failed`; terminal states cannot transition. Lifecycle-dependent fields remain nullable until populated. |
| Finding identity | UUID primary key and unique `(analysis_id, fingerprint)` to prevent duplicate deterministic evidence within one run. |
| Relationships | Indexed foreign keys; repository/analysis and analysis/finding ownership uses explicit cascading deletes, with no delete API in this phase. |
| Query indexes | Repository `created_at`; analysis `(repository_id, created_at)` and `(status, created_at)`; finding `(analysis_id, severity)` and `(analysis_id, file_path)`. |
| Pagination | Bounded offset/limit (`limit <= 100`) with a stable `created_at, id` order and `{items, total, offset, limit}` responses. |
| API slice | Add repository create/list and nested analysis create/list routes. Analysis creation persists `queued` state only; enqueueing remains Prompt 05. Findings have persistence support but no public routes yet. |
| Test isolation | Use a dedicated disposable PostgreSQL test database, migrate it to `head`, and roll each integration test back; CI provisions PostgreSQL and verifies the migration head. |

Provide `alembic upgrade head` from `backend/` as the authoritative migration command,
plus a small PowerShell development wrapper. Preserve stable application errors for
duplicate repositories, missing parents, and invalid transitions.

The implementation is very likely to exceed the 400 changed-line review budget.
Because the configured strategy is `ask-always`, obtain a delivery decision before
APPLY. Prefer three reviewable slices: (1) database/model/migration foundation, (2)
contracts/services/API, and (3) integration tests/CI/documentation.

### Risks
- Prompt 03 does not define exact API payloads, provider/visibility vocabularies, or
  pagination envelopes; proposal/spec must freeze these before implementation.
- Exact clone-URL uniqueness cannot collapse semantic URL aliases until Prompt 04 adds
  secure validation and canonicalization.
- Per-test async transaction rollback is subtle when application code commits; the
  design must specify savepoint-compatible test sessions or use disposable schemas.
- A migration can look correct from ORM tests while failing on a clean database; CI must
  run `alembic upgrade head` against PostgreSQL, not SQLite or `metadata.create_all()`.
- The current non-3.13 host cannot run project checks directly; implementation should use
  a Python 3.13 environment or a purpose-built test container.

### Ready for Proposal
Yes. The proposal should adopt the layered approach, explicitly define transport
contracts and enum vocabularies, preserve Prompt 04/05 boundaries, record the Luna/high
APPLY constraint, and flag the required chained-PR decision before implementation.
