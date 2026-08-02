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

# Prompt 02 — Configuration, logging and error handling

## Goal

Build a reliable application foundation for configuration, structured logging, request correlation and consistent API errors.

## Preconditions

Prompt 01 should already be implemented. Inspect the current repository and adapt to its real structure.

## Tasks

1. Implement typed application settings using Pydantic Settings.
2. Support:
   - application environment
   - database URL
   - Redis URL
   - Celery broker and result backend
   - logging level and format
   - CORS origins
   - repository analysis limits
   - optional LLM settings
3. Validate dangerous or inconsistent production configuration.
4. Add structured logging with Structlog.
5. Add request correlation IDs:
   - accept an incoming correlation header when valid
   - generate one otherwise
   - return it in the response
   - include it in logs
6. Add centralized exception handling for:
   - validation errors
   - domain/application errors
   - unexpected errors
7. Define a stable error response contract.
8. Ensure secrets are never rendered in logs or settings representations.
9. Add unit and API tests for configuration and error handling.
10. Update `.env.example`, README and architecture documentation.

## Constraints

- Do not add authentication yet.
- Do not initialize external telemetry vendors.
- Logging configuration must work locally and in containers.
- Error messages exposed to clients must not reveal stack traces or secrets.

## Acceptance criteria

- Invalid required configuration fails early with a useful message.
- Every API response includes a correlation ID.
- Structured logs include correlation ID, method, path, status and duration.
- Expected application errors use the documented error schema.
- Unexpected exceptions return a generic 500 response.
- Tests, Ruff and Mypy pass.
