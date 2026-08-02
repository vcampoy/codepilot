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

# Prompt 12 — MVP frontend dashboard

## Goal

Build a polished but focused React interface for the current backend capabilities.

## Required views

1. Repository list.
2. Add public repository form.
3. Repository detail.
4. Analysis history.
5. Analysis status with polling.
6. Analysis overview:
   - risk score
   - findings by severity
   - analyzed files
   - duration
   - analyzer status
7. Hotspot table.
8. Findings table with filters.
9. File detail with score breakdown.
10. Bounded dependency graph visualization.
11. Quality-gate result.

## Tasks

1. Introduce a clean frontend architecture.
2. Generate typed API clients from OpenAPI or implement strongly typed contracts.
3. Add server-state handling and clear loading/error/empty states.
4. Add routing.
5. Add accessible forms and tables.
6. Add responsive layouts.
7. Add frontend tests for critical flows.
8. Avoid unnecessary design-system complexity.
9. Add screenshots or placeholder instructions to the README.
10. Ensure the frontend contains no provider secrets.

## Constraints

- Do not add authentication yet unless already required by the repository.
- Do not display fake production metrics.
- Avoid unbounded graph rendering.
- Prioritize clarity over animation.

## Acceptance criteria

- A user can submit a repository and follow analysis progress.
- Completed analyses have readable overview, hotspot and finding views.
- API errors are shown meaningfully.
- The frontend builds and tests pass.
- Linting and TypeScript checks pass.
