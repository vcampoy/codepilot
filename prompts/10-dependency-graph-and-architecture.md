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

# Prompt 10 — Dependency graph and architecture insights

## Goal

Build repository-level structural intelligence without pretending to fully understand every framework.

## Initial supported graph extraction

Prioritize:

- Python imports
- TypeScript/JavaScript imports
- C# namespace/project references where available without compiling

## Tasks

1. Define graph domain models:
   - nodes
   - edges
   - node type
   - edge type
   - source analyzer
2. Implement language-specific import/reference extractors.
3. Build module/file dependency graphs.
4. Calculate:
   - in-degree and out-degree
   - strongly connected components
   - dependency cycles
   - highly coupled nodes
   - isolated nodes where meaningful
5. Persist graph summaries, not necessarily every huge raw graph without limits.
6. Expose graph APIs with pagination or bounded responses.
7. Add architecture findings for:
   - dependency cycles
   - excessive fan-out
   - excessive fan-in with clear caveats
8. Add graph fixture tests.
9. Add limits for very large repositories.
10. Document that this is structural analysis, not complete semantic understanding.

## Constraints

- Use a deterministic graph library such as NetworkX if appropriate.
- Do not require successful project compilation.
- Avoid framework-specific claims unless supported by evidence.
- Every architecture finding must link to graph evidence.

## Acceptance criteria

- Fixture projects generate expected nodes and edges.
- Known dependency cycles are detected.
- Graph endpoints remain bounded for large inputs.
- Architecture findings expose exact supporting edges.
- Tests, Ruff and Mypy pass.
