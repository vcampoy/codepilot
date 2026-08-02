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

# Prompt 15 — Public MVP hardening and release readiness

## Goal

Prepare CodePilot for a credible public GitHub release and limited public deployment.

## MVP definition

A user can:

1. Create an account or use the chosen minimal authentication flow.
2. Connect or submit a public GitHub repository.
3. Run an asynchronous deterministic analysis.
4. Inspect findings, hotspots, architecture indicators and explainable risk.
5. Compare against a baseline.
6. Optionally request AI explanations.
7. Receive a GitHub Check for pull requests.

## Tasks

1. Perform a complete repository audit.
2. Add the minimum authentication and workspace model required for safe public use.
3. Add authorization checks to all tenant-owned resources.
4. Add:
   - API rate limits
   - repository and analysis quotas
   - upload limits
   - concurrency limits
5. Add security protections:
   - secret redaction
   - safe headers
   - dependency scanning
   - container hardening
   - non-root runtime
   - SSRF regression tests
6. Add OpenTelemetry instrumentation.
7. Add error reporting integration behind configuration.
8. Add health, readiness and liveness endpoints.
9. Add integration and end-to-end test coverage for the primary user flow.
10. Add performance tests for a representative medium repository.
11. Improve:
   - README
   - architecture docs
   - ADRs
   - contribution guide
   - security policy
   - code of conduct
   - license recommendation
12. Add demo screenshots and an example repository.
13. Add production deployment documentation for:
   - frontend
   - API
   - worker
   - PostgreSQL
   - Redis
   - object storage if used
14. Review CI and add release-quality checks.
15. Produce a final MVP gap analysis.

## Constraints

- Do not claim production readiness unless the evidence supports it.
- Do not add enterprise features.
- Avoid infrastructure that is unnecessarily expensive for an MVP.
- Preserve local Docker Compose development.

## Acceptance criteria

- The main end-to-end flow is automated and passing.
- Tenant data cannot be accessed across workspaces.
- Public endpoints have appropriate limits.
- Containers run as non-root where practical.
- Documentation allows another engineer to run the project locally.
- CI is green.
- The final report lists remaining limitations honestly.
