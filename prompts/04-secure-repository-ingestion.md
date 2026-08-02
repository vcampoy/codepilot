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

# Prompt 04 — Secure repository ingestion

## Goal

Allow CodePilot to ingest public Git repositories safely and prepare them for asynchronous analysis.

## Scope

Support public Git HTTPS URLs only in this phase.

## Tasks

1. Add a repository ingestion service that:
   - validates supported URL schemes
   - rejects local paths and file URLs
   - mitigates SSRF and access to private/internal network targets
   - clones with a strict timeout
   - limits repository size and file count
   - supports shallow cloning where appropriate
   - resolves the analyzed commit SHA
2. Clone into an isolated temporary working directory.
3. Guarantee cleanup after success, failure, timeout or cancellation.
4. Detect:
   - primary languages
   - file count
   - approximate source size
   - default branch when available
5. Implement ignore rules for:
   - `.git`
   - dependencies/vendor folders
   - build outputs
   - generated files where detectable
6. Introduce explicit domain errors for ingestion failures.
7. Add tests using local temporary Git repositories.
8. Add security documentation describing the threat model.

## Constraints

- Do not add GitHub OAuth yet.
- Do not use shell command strings assembled from user input.
- Prefer a safe subprocess argument list or a well-supported Git library.
- Repository content is untrusted.
- Never execute repository code during ingestion.

## Acceptance criteria

- A valid public repository URL can be cloned and inspected.
- Unsupported schemes, localhost and private network targets are rejected.
- Timeout, maximum size and file-count limits are enforced.
- Temporary directories are always removed.
- The resolved commit SHA is persisted.
- Tests, Ruff and Mypy pass.
