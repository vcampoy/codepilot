# MVP deployment guide

## Local Compose

`docker compose up --build` runs PostgreSQL, Redis, the migration job, API, Celery worker, Beat, and the static frontend. The migration service must complete before API and worker services start. Use `docker compose down` to stop the stack.

## API and worker

Build the backend image from `backend/`. Run the API with Uvicorn and the worker with Celery using the same environment values for PostgreSQL, Redis, repository limits, authentication, and optional integrations. Run `alembic upgrade head` before deploying a new application revision. The backend image uses a non-root `codepilot` user; Compose also drops Linux capabilities and enables `no-new-privileges` for application containers.

## Frontend

Build `frontend/` with `VITE_API_BASE_URL` set to the public API origin, then serve the generated `dist/` directory behind a TLS-terminating reverse proxy. The current Nginx image is a static MVP server; add a platform-specific non-root Nginx configuration before a hardened production deployment.

## PostgreSQL and Redis

Use managed PostgreSQL and Redis for public deployment, rotate credentials through the platform secret manager, and restrict network access to API and worker services. Enable encrypted connections in production. PostgreSQL is the source of truth; Redis carries Celery delivery state and must not be treated as durable analysis storage.

## Object storage

The current MVP does not persist repository archives or user uploads to object storage. If added, use private buckets, short-lived signed URLs, lifecycle deletion, encryption at rest, and a workspace-prefixed key namespace.

## Readiness and operations

Use `/health/live` for process liveness and `/health/ready` for service readiness. Configure JSON logs, correlation IDs, metrics/traces, and error reporting only through deployment configuration. Review `docs/mvp-gap-analysis.md` before claiming production readiness.
