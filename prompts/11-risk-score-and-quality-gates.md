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

# Prompt 11 — Explainable risk score and quality gates

## Goal

Create CodePilot's first proprietary but transparent risk model and configurable quality gates.

## Risk Score v1

Use a documented weighted model based on normalized values such as:

- complexity
- recent churn
- finding severity/density
- coupling
- ownership concentration risk
- optional missing coverage only when coverage data exists

Do not invent data.

## Tasks

1. Design versioned risk score configuration.
2. Define normalization strategies and edge cases.
3. Calculate file-level and repository-level risk.
4. Persist:
   - final score
   - score version
   - every component value
   - configured weights
5. Add risk categories with documented thresholds.
6. Implement configurable quality gates:
   - maximum new critical findings
   - maximum risk score
   - maximum new debt estimate only if a defensible estimate exists
   - maximum number of new hotspots
7. Compare an analysis with a baseline commit/analysis.
8. Expose quality-gate results and failures through the API.
9. Add property-based or thorough boundary tests where useful.
10. Write `docs/risk-score.md`.

## Constraints

- Never hide the score formula.
- Do not claim scientific or predictive certainty.
- Avoid fake precision.
- Quality gates should prioritize newly introduced problems over legacy debt.

## Acceptance criteria

- Every displayed score can be reconstructed from stored components.
- Changing weights produces predictable tested results.
- Baseline comparison distinguishes existing from new findings.
- Quality-gate failure reasons are explicit.
- Tests, Ruff and Mypy pass.
