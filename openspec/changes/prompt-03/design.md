# Design: Async Persistence Model and Alembic Foundation

## Technical Approach

Add a narrow hexagonal slice: FastAPI routes call use-case services, services depend on repository/unit-of-work protocols, and SQLAlchemy adapters map private ORM rows to framework-independent domain records. PostgreSQL is authoritative; one async session is used per request/task. This implements both delta specs without cloning, ref resolution, enqueueing, workers, or public finding behavior.

## Architecture Decisions

| Decision | Alternative / tradeoff | Choice and rationale |
|---|---|---|
| Persistence boundary | Route-level ORM is smaller but violates `api -> services` | Keep ORM in `db/models.py`; map at `repositories/sqlalchemy.py` so domain/API never expose SQLAlchemy. |
| Transaction owner | Repository commits obscure atomic use cases | A `UnitOfWork` protocol owns `commit`/`rollback`; the dependency owns session closure. Creates flush before commit so named constraint failures are translated safely. |
| Lifecycle | Database-only checks cannot express transition intent | `Analysis.transition(...)` validates and computes all replacement fields before mutation; DB checks provide defense in depth. |
| Enum storage | Native PostgreSQL enums complicate rollback | Use typed Python enums mapped to named `VARCHAR` check constraints; values remain constrained and downgrade is table-only. |
| Test isolation | Truncation is slow and race-prone | Bind each test session to an outer transaction with `join_transaction_mode="create_savepoint"`; service commits release savepoints and fixture rollback removes data. |

## Data and Transaction Flow

```text
HTTP -> schema -> service -> UnitOfWork -> SQLAlchemy adapter -> PostgreSQL
                    |             |
                    +-- domain ---+-- commit or rollback
```

`db/session.py` normalizes only a leading `postgresql://` to `postgresql+asyncpg://`, builds one `AsyncEngine` and `async_sessionmaker(expire_on_commit=False)`. `migrations/env.py` reuses that normalizer, reads `Settings` at command time, targets ORM metadata, and uses an async `NullPool`; `alembic.ini` stores no URL. `main.py` creates the runtime objects in the composition root; lifespan disposes the engine. `api/dependencies.py` opens one session, yields a SQLAlchemy unit of work, rolls back through it on exceptions, and always closes the session. Read services do not commit. Create services flush, then commit once; duplicate, validation, and missing-parent paths roll back completely.

## Persistence Model

| Table | Mapping and constraints |
|---|---|
| `repositories` | UUID PK; bounded trimmed text; provider/visibility checks; UTC `created_at`/`updated_at`; unique `(provider, clone_url)`; `created_at` index. |
| `analyses` | UUID PK; cascading indexed `repository_id`; bounded `requested_ref`; status check; nullable lifecycle fields; checks enforce queued/running/terminal timestamp and failure-field combinations; indexes `(repository_id, created_at)` and `(status, created_at)`. |
| `findings` | UUID PK; cascading indexed `analysis_id`; non-empty text; positive nullable line/column; JSONB objects; severity check; unique `(analysis_id, fingerprint)`; indexes `(analysis_id, severity)` and `(analysis_id, file_path)`. |

All timestamps use `TIMESTAMP WITH TIME ZONE` and UTC application defaults; JSON uses PostgreSQL JSONB. Domain transitions are exactly `queued -> running|failed` and `running -> completed|failed`; invalid transitions raise `invalid_analysis_transition` before state changes.

## Interfaces and HTTP Contracts

`repositories/contracts.py` defines typed `RepositoryStore`, `AnalysisStore`, `FindingStore`, `Page[T]`, and `UnitOfWork` protocols. `services/repositories.py` provides create/list use cases; `services/analyses.py` provides nested create/list plus reusable transition logic for Prompt 05. Lists execute scoped `count` and item queries ordered by `created_at ASC, id ASC`, with offset/limit supplied by validated transport input.

`api/v1/schemas.py` uses `extra="forbid"`, enum types, strict trimmed-length validators, exact response fields, and generic `{items,total,offset,limit}` models. `api/v1/repositories.py` owns `POST/GET /repositories` and `POST/GET /repositories/{repository_id}/analyses`; creates return 201 and analyses remain queued with null lifecycle fields. `api/errors.py` maps semantic errors to existing envelopes: named unique-constraint races to `409 repository_already_exists`, absent parents to `404 repository_not_found`, and FastAPI validation (including UUID/query bounds) remains the safe 422 handler.

## File Changes

| Files | Action |
|---|---|
| `backend/src/codepilot/{domain/models.py,db/session.py,db/models.py}` | Create domain invariants, runtime DB lifecycle, and ORM mappings. |
| `backend/src/codepilot/{repositories/contracts.py,repositories/sqlalchemy.py,services/repositories.py,services/analyses.py}` | Create ports, adapters/UoW, and use cases. |
| `backend/src/codepilot/api/{dependencies.py,errors.py,v1/schemas.py,v1/repositories.py,v1/router.py}`, `backend/src/codepilot/main.py` | Create HTTP wiring/contracts; modify the v1 router/composition root. |
| `backend/{alembic.ini,migrations/env.py,migrations/script.py.mako,migrations/versions/0001_initial_persistence.py}` | Create credential-free async Alembic setup and reversible schema. |
| `backend/tests/{conftest.py,test_domain.py,test_repositories.py,test_api_repositories.py,test_migrations.py}` | Create unit and PostgreSQL integration coverage. |
| `backend/pyproject.toml`, `.github/workflows/ci.yml`, `backend/scripts/migrate.ps1`, `README.md`, `docs/architecture.md` | Add async test support, PostgreSQL CI, migration command, and current architecture docs. |

## Testing and Rollout

CI provisions disposable PostgreSQL, exports `TEST_DATABASE_URL`, runs `alembic upgrade head`, and then Ruff, format, Mypy, and pytest. A session fixture performs upgrade/downgrade/re-upgrade; per-test outer transactions isolate repository and async HTTPX API tests. Tests inspect constraints/indexes and cover races, cascades, round trips, lifecycle atomicity, pagination, exact responses, and safe errors.

Run from `backend/`: `alembic upgrade head`; the PowerShell wrapper provides the same development action. Rollback stops writes, downgrades to `base` (children before parents), and reverts route/wiring changes; this destructively removes Prompt 03 data.

Prompt 04 retains URL validation/canonicalization, cloning, and SHA resolution. Prompt 05 retains enqueueing, worker transitions, retries, summaries, and status semantics. Before APPLY, resolve the ask-always chained-PR decision; APPLY MUST use `openai/gpt-5.6-luna`, variant `high`.

## Open Questions

None.
