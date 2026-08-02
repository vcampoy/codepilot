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

# Prompt 07 — Python static analysis adapters

## Goal

Add credible Python analysis by integrating established deterministic tools instead of reimplementing them.

## Tools

Integrate, where technically compatible:

- Ruff
- Bandit
- Radon

## Tasks

1. Implement adapters for each tool behind the analyzer contract.
2. Use machine-readable output formats.
3. Normalize results into CodePilot findings.
4. Capture tool version and execution duration.
5. Map severities and categories consistently.
6. Support configuration with secure defaults.
7. Add Python metrics:
   - cyclomatic complexity
   - maintainability-related metrics where reliable
   - source lines
8. Handle:
   - missing tools
   - unsupported syntax
   - timeouts
   - malformed output
9. Create representative fixture repositories.
10. Add tests for parsing, normalization and fingerprint stability.
11. Document which findings come from external tools versus CodePilot logic.

## Constraints

- Never run tests or application code from the target repository.
- Avoid invoking tools in a way that imports target modules.
- Do not claim security guarantees beyond Bandit's actual scope.
- Preserve original rule identifiers.

## Acceptance criteria

- A Python fixture repository produces normalized Ruff, Bandit and Radon results.
- Tool absence creates an explicit analyzer availability state.
- Findings point to correct paths and positions.
- Severity mapping is documented and tested.
- Tests, Ruff and Mypy pass.
