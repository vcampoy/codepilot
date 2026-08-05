# Python analysis adapters

CodePilot invokes Ruff, Bandit, and Radon through fixed subprocess argument lists and parses their machine-readable output. The adapters never import or execute modules from the analyzed repository.

| Adapter | Output | Category mapping | Scope |
| --- | --- | --- | --- |
| Ruff | JSON diagnostics | `E`/`F` = error, `W` = warning, other rules = info | Lint and style |
| Bandit | JSON security results | LOW = info, MEDIUM = warning, HIGH = error | Security checks implemented by Bandit |
| Radon | JSON complexity/MI reports | Complexity ≥ 10 = warning, ≥ 15 = error | Cyclomatic complexity and maintainability metrics |

Tool absence is returned as an explicit unavailable execution state. Malformed output becomes a partial analyzer failure. Tool timeouts are isolated by the analyzer orchestrator and do not discard findings from other analyzers.

Ruff, Bandit, and Radon findings retain the original rule identifier. CodePilot-generated generic findings use the `GEN` rule namespace and are distinguishable from external-tool results.

Bandit findings describe only the checks Bandit actually performs; CodePilot does not extend them into a general security guarantee.
