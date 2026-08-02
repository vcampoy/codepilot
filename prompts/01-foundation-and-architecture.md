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

# Prompt 01 — Foundation and architecture baseline

## Goal

Create or normalize the initial production-quality monorepo foundation for **CodePilot**, an AI-assisted code intelligence platform.

Repository description:

> AI-powered code intelligence platform that analyzes repositories, detects technical debt, explains architecture, and provides actionable refactoring insights.

The product must remain useful without any LLM configured. Deterministic analysis is the source of truth; AI only explains and prioritizes evidence.

## Target stack

### Backend

- Python 3.13
- FastAPI
- Pydantic v2
- SQLAlchemy 2 async
- PostgreSQL
- Redis
- Celery
- Alembic
- Structlog
- Pytest
- Ruff
- Mypy

### Frontend

- React
- TypeScript
- Vite

### Infrastructure

- Docker
- Docker Compose
- GitHub Actions

## Tasks

1. Inspect the repository and report its current state before modifying it.
2. Establish a clear monorepo structure:
   - `backend/`
   - `frontend/`
   - `docs/`
   - `.github/workflows/`
3. Create or normalize:
   - root `README.md`
   - `.gitignore`
   - `.editorconfig`
   - `.env.example`
   - `docker-compose.yml`
   - backend `pyproject.toml`
   - frontend package configuration
4. Create a minimal FastAPI application with:
   - application factory or clean app bootstrap
   - `/health`
   - versioned API router
5. Create a Celery application bootstrap.
6. Create a minimal React page that identifies the project and links to API documentation.
7. Add backend and frontend CI jobs.
8. Document the initial architecture in `docs/architecture.md`.
9. Add ADR 0001:
   - deterministic analysis before AI enrichment
10. Create a detailed `ROADMAP.md` covering all remaining phases through public MVP.

## Architecture constraints

Use clear boundaries:

- `api`
- `core`
- `db`
- `domain`
- `repositories`
- `services`
- `analyzers`
- `worker`
- `llm`
- `github`

Do not create artificial abstractions without a current use case.

## Acceptance criteria

- `docker compose config` succeeds.
- FastAPI starts and `/health` returns HTTP 200.
- The worker can import its Celery application.
- Backend tests pass.
- Ruff passes.
- Mypy passes on the current backend scope.
- Frontend builds successfully.
- CI workflow reflects the same local checks.
- The repository contains no real credentials.
