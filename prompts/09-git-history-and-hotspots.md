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

# Prompt 09 — Git history intelligence and hotspots

## Goal

Use repository history to identify files that are both difficult and frequently changed.

## Metrics

Implement deterministic metrics for:

- commit count per file
- recent change frequency
- author count
- ownership concentration
- file age
- recent churn
- rename-aware history where practical

## Tasks

1. Build a Git history service that does not depend on GitHub APIs.
2. Define configurable time windows.
3. Normalize file paths across renames when reasonably possible.
4. Persist per-file history metrics for an analysis.
5. Define a hotspot score combining:
   - complexity or finding density
   - recent churn
6. Expose:
   - top hotspots
   - history metric breakdown
   - score explanation
7. Add unit tests with generated Git histories.
8. Add performance limits for large histories.
9. Document metric limitations and biases.
10. Update the dashboard API contracts, but do not build the full frontend yet.

## Constraints

- Do not present author count as a measure of individual performance.
- Do not infer developer quality.
- Scores must be explainable and configurable.
- Use bounded history traversal.

## Acceptance criteria

- Fixture repositories with known commit histories produce expected metrics.
- Hotspots rank high-complexity, frequently changed files above stable files.
- Every hotspot exposes its component metrics.
- Large histories respect configured limits.
- Tests, Ruff and Mypy pass.
