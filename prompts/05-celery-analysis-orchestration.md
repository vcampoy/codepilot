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

# Prompt 05 — Asynchronous analysis orchestration

## Goal

Implement a robust, idempotent analysis workflow using Celery and Redis.

## Workflow

```text
API request
  -> create analysis record
  -> enqueue task
  -> clone repository
  -> run analyzers
  -> persist findings
  -> calculate summary
  -> mark completed or failed
```

## Tasks

1. Implement an application service for requesting an analysis.
2. Implement the Celery task and orchestration flow.
3. Enforce valid state transitions:
   - queued
   - running
   - completed
   - failed
   - cancelled only if already supported cleanly
4. Add idempotency:
   - duplicate delivery must not duplicate findings
   - retrying a failed task must be safe
5. Use deterministic finding fingerprints.
6. Add retry policies only for transient failures.
7. Separate safe user-facing failure messages from internal logs.
8. Add analysis status and summary endpoints.
9. Persist basic summary metrics:
   - analyzed file count
   - source lines
   - finding count by severity
   - duration
10. Add worker integration tests.

## Constraints

- Do not return Celery result payloads as the product source of truth.
- PostgreSQL is the source of truth for analysis state.
- Do not pass repository content through Redis.
- Tasks must clean temporary resources.
- Do not add AI yet.

## Acceptance criteria

- Analysis API responds with HTTP 202 and a persisted analysis ID.
- Worker updates state and persists findings.
- Duplicate task execution does not duplicate findings.
- Failures are persisted and observable.
- Retriable and non-retriable errors are distinguished.
- Tests, Ruff and Mypy pass.
