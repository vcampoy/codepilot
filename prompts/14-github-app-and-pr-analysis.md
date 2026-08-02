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

# Prompt 14 — GitHub integration and pull-request analysis

## Goal

Integrate CodePilot with GitHub so users can select repositories and receive focused pull-request feedback.

## Preferred integration

Use a GitHub App rather than storing broad personal access tokens.

## Tasks

1. Implement GitHub App configuration and installation flow.
2. Securely store only necessary installation metadata and encrypted tokens if persistence is required.
3. Add repository discovery for installed accounts.
4. Implement signed webhook verification.
5. Handle:
   - push events
   - pull request opened/synchronize/reopened events
6. Ensure webhook idempotency.
7. Implement diff-focused PR analysis:
   - new findings
   - resolved findings
   - risk delta
   - new hotspots
   - quality-gate result
8. Publish a concise GitHub Check.
9. Avoid posting noisy inline comments by default.
10. Add rate-limit handling and backoff.
11. Add mocked integration tests.
12. Document local webhook development and required GitHub App permissions.

## Constraints

- Request the minimum GitHub permissions.
- Never log installation tokens or webhook secrets.
- Do not expose private repository content to an LLM unless explicitly enabled and documented.
- A GitHub event must not trigger duplicate analyses.
- External GitHub calls must be behind a dedicated adapter.

## Acceptance criteria

- Invalid webhook signatures are rejected.
- Replayed events are idempotent.
- A PR fixture produces a baseline comparison and quality-gate result.
- GitHub Check output is concise and links to the CodePilot analysis.
- Tests, Ruff and Mypy pass.
