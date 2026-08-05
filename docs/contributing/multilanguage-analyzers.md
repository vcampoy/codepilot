# Multilanguage adapters

CodePilot accepts normalized ESLint JSON and SARIF 2.1.0 results. SARIF is the preferred path for Roslyn analyzers and `dotnet format analyzers`: import an existing artifact instead of restoring dependencies or running arbitrary MSBuild targets.

## Safety rules

- Never run `npm install` against an analyzed repository.
- Never invoke arbitrary build scripts or MSBuild targets.
- Limit SARIF uploads by bytes and nesting depth before processing.
- Keep original ESLint/SARIF rule identifiers and stable fingerprints.

The `GET /api/v1/analyses/analyzers/availability` endpoint reports whether optional executables are present in the worker image. An unavailable tool is reported as `skipped`; malformed tool output is represented as an analyzer failure rather than a failed complete analysis.
