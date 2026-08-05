# CodePilot Project Context

CodePilot is an evidence-first code intelligence monorepo. The current implementation
is an executable foundation; repository ingestion, persistence behavior, analyzers,
dashboards, GitHub integration, and AI enrichment remain later roadmap phases.

## Stack and Runtime

| Area | Current implementation |
| --- | --- |
| Backend | Python 3.13, FastAPI, Pydantic Settings, Structlog, Celery |
| Persistence dependencies | SQLAlchemy async, asyncpg, Alembic; PostgreSQL provisioned by Compose |
| Worker infrastructure | Celery with Redis broker/result backend |
| Frontend | React 19, TypeScript strict mode, Vite 8 |
| Local runtime | Docker Compose with API, worker, PostgreSQL, Redis, and Nginx-served frontend |

## Conventions

- Backend source uses a `src/` layout and 4-space Python indentation.
- Frontend uses strict TypeScript, 2-space formatting, and Vite module resolution.
- Backend quality gates are Ruff lint/format checks, Mypy strict type checking, and pytest.
- CI is authoritative for backend and frontend verification commands.
- SDD artifacts live under `openspec/`; skill indexing lives under `.atl/skill-registry.md`.
- Documentation and repository artifacts are written in English.

## Architecture

The backend uses explicit boundaries: `api`, `core`, `worker`, `services`, `domain`,
`repositories`, `db`, `analyzers`, `llm`, and `github`. Only the API/core/worker
foundation is operational today. Future services coordinate use cases, the domain
remains framework-independent, repositories isolate persistence, analyzers produce
deterministic evidence, and LLM/GitHub integrations remain outbound adapters.

The frontend communicates through the public API contract and does not access backend
internals or infrastructure services. Deterministic analysis is authoritative; optional
AI enrichment may explain or prioritize stored evidence but must not replace it.

## Current API and Cross-Cutting Contracts

- `GET /health` returns deterministic health status.
- `GET /api/v1/` exposes versioned discovery metadata.
- Every HTTP response carries `X-Correlation-ID`.
- Errors use a stable `{ "error": { "code", "message", "correlation_id", "details"? } }` envelope.
- Settings use typed Pydantic configuration and protect secrets from representations/logs.

## Testing and Strict TDD

| Capability | Status | Command/tool |
| --- | --- | --- |
| Unit tests | Available | `python -m pytest` |
| Integration tests | Available | FastAPI `TestClient`/HTTPX under pytest |
| E2E tests | Not detected | — |
| Coverage | Not configured | — |
| Backend lint/format | Available | `ruff check .`; `ruff format --check .` |
| Backend type checking | Available | `mypy` |
| Frontend type/build check | Available | `npm run build` |

Strict TDD is disabled by the existing OpenSpec configuration. Backend test dependencies
are declared in `backend/pyproject.toml`, but the current host Python environment does
not have pytest installed; CI and the container workflow install the declared dev set.
