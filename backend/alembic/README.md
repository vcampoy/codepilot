# Analysis schema deployment

Run the migration before starting the API or Celery worker:

```powershell
alembic upgrade head
```

The command reads `DATABASE_URL` through the application settings. The
`codepilot_analyses` and `codepilot_analysis_findings` tables are the PostgreSQL
source of truth for Prompt 05. Runtime code does not call `metadata.create_all`;
schema changes must be delivered as migrations.

The deployed Compose stack runs this command in its `migration` service and
starts the API, worker, and Celery beat only after that service succeeds. Celery
beat periodically invokes `codepilot.analysis.recover_stale` so crashed workers
and queued requests whose delivery could not be confirmed are repaired without
waiting for a new API request.
