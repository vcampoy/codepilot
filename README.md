# CodePilot

CodePilot is an evidence-first code intelligence platform that analyzes repositories, detects technical debt, explains architecture, and provides actionable refactoring insights. Deterministic analysis remains the source of truth; optional AI enrichment will explain and prioritize that evidence without replacing it.

## Quick start

The complete local baseline runs with Docker Compose:

```bash
docker compose up --build
```

Once the services are healthy:

| Service | URL |
| --- | --- |
| Frontend | <http://localhost:5173> |
| API health | <http://localhost:8000/health> |
| API v1 | <http://localhost:8000/api/v1/> |
| API documentation | <http://localhost:8000/docs> |

Stop the stack with `docker compose down`. Add `--volumes` only when you also want to remove local PostgreSQL and Redis data.

## Repository layout

```text
backend/            FastAPI API, Celery worker, domain boundaries and tests
frontend/           React and TypeScript application built with Vite
docs/               Architecture documentation and decision records
.github/workflows/  Continuous integration checks
prompts/             Ordered delivery prompts for the public MVP
```

The current phase establishes executable foundations only. Persistence, repository ingestion, analyzers, AI enrichment, and GitHub integration are intentionally deferred to the phases in [`ROADMAP.md`](ROADMAP.md).

## Local development

### Backend

Python 3.13 is required.

```bash
cd backend
python -m venv .venv
python -m pip install -e ".[dev]"
uvicorn codepilot.main:app --reload
```

Run the backend quality checks from `backend/`:

```bash
pytest
ruff check .
ruff format --check .
mypy
```

Start a worker after Redis is available:

```bash
celery -A codepilot.worker.celery_app:celery_app worker --loglevel=INFO
```

### Frontend

Node.js `20.19+` or `22.12+` is required.

```bash
cd frontend
npm ci
npm run dev
```

Set `VITE_API_BASE_URL` before building when the API is not available at `http://localhost:8000`.

## Configuration

Copy `.env.example` to `.env` to override Compose defaults. The checked-in values are development-only placeholders; never commit real credentials.

## Architecture

- [`docs/architecture.md`](docs/architecture.md) describes components and dependency boundaries.
- [`docs/adr/0001-deterministic-analysis-before-ai.md`](docs/adr/0001-deterministic-analysis-before-ai.md) records the evidence-first product decision.
- [`ROADMAP.md`](ROADMAP.md) defines the remaining delivery phases through public MVP.

## License

CodePilot is licensed under the terms in [`LICENSE`](LICENSE).
