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
| API liveness | <http://localhost:8000/health/live> |
| API readiness | <http://localhost:8000/health/ready> |
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

The repository contains the ordered MVP phases in [`prompts/`](prompts/). Review the honest release limitations in [`docs/mvp-gap-analysis.md`](docs/mvp-gap-analysis.md) before deploying publicly.

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

The dashboard uses hash-based navigation so it can be served as static Vite output without a router server. To capture a local screenshot for review, run `npm run dev`, open the dashboard, submit a public HTTPS repository, and capture the overview after the API reports a completed analysis. Empty states are intentional when an endpoint has not returned evidence; the UI does not fabricate production metrics.

## Configuration

Copy `.env.example` to the repository root as `.env` to override Docker Compose defaults. Compose consumes that root `.env` for variable interpolation and passes the resulting values to the API and worker containers. The checked-in values are development-only placeholders; never commit real credentials.

For a backend started locally from `backend/`, Pydantic Settings reads an env file named `.env` relative to the process working directory, so use `backend/.env` (or export environment variables) for local backend settings. The root `.env` is not automatically loaded by that command.

### Runtime reference

| Variable | Meaning | Default |
| --- | --- | --- |
| `ENVIRONMENT` | `development`, `test`, `staging`, or `production` | `development` |
| `DATABASE_URL` | PostgreSQL DSN; treated as a secret | local PostgreSQL DSN |
| `REDIS_URL` | Redis DSN; treated as a secret | `redis://localhost:6379/0` |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | Celery Redis DSNs; treated as secrets | Redis databases `0` / `1` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` | `INFO` |
| `LOG_FORMAT` | `console` or `json` | `console` |
| `CORS_ORIGINS` | Comma-separated allowed origins | `http://localhost:5173` |
| `REPOSITORY_MAX_SIZE_BYTES` | Maximum repository size | `100000000` |
| `REPOSITORY_MAX_FILE_COUNT` | Maximum repository file count | `50000` |
| `ANALYSIS_TIMEOUT_SECONDS` | Analysis time limit | `300` |
| `LLM_ENABLED` | Enables optional LLM enrichment | `false` |
| `LLM_PROVIDER` / `LLM_MODEL` / `LLM_API_KEY` | LLM provider settings; API key is secret | unset |
| `AUTH_REQUIRED` / `AUTH_API_KEY` | Minimal public API-key authentication | `false` / unset |
| `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS` | In-process public request limit | `120` / `60` |
| `WORKSPACE_ANALYSIS_QUOTA` | Accepted analyses per workspace | `100` |
| `GITHUB_ENABLED` / `GITHUB_APP_ID` | Optional GitHub App integration | `false` / unset |
| `OBSERVABILITY_ENABLED` / `ERROR_REPORTING_DSN` | Optional traces and error reporting | `false` / unset |

Production requires JSON logging, non-local service URLs, non-default database credentials, HTTPS-only non-wildcard CORS origins, API-key authentication, and complete LLM settings when LLM configuration is supplied. LLM enrichment and GitHub integration are disabled by default. See [`docs/deployment.md`](docs/deployment.md) and [`SECURITY.md`](SECURITY.md).

### Request errors

Each HTTP response carries `X-Correlation-ID`. A valid incoming value is retained; otherwise the API generates one. Structured access logs include the correlation ID, method, path, status, and duration.

Errors use this stable envelope; `details` is optional:

```json
{
  "error": {
    "code": "request_validation_error",
    "message": "Request validation failed.",
    "correlation_id": "request-42",
    "details": [
      {"location": ["body", "name"], "message": "Field required", "type": "missing"}
    ]
  }
}
```

Validation details omit rejected values and request bodies. Unexpected failures return the generic `internal_server_error` message and do not expose stack traces or secrets.

## Architecture

- [`docs/architecture.md`](docs/architecture.md) describes components and dependency boundaries.
- [`docs/adr/0001-deterministic-analysis-before-ai.md`](docs/adr/0001-deterministic-analysis-before-ai.md) records the evidence-first product decision.
- [`ROADMAP.md`](ROADMAP.md) defines the remaining delivery phases through public MVP.

## License

CodePilot is licensed under the terms in [`LICENSE`](LICENSE).
