# Adding a deterministic analyzer

Analyzers inspect the isolated repository snapshot without executing repository code.
Register explicit implementations in an `AnalyzerRegistry`; arbitrary dynamic plugin loading is intentionally unsupported.

## Quick path

1. Implement `Analyzer` with stable `AnalyzerMetadata`.
2. Return `NormalizedFinding` values and deterministic `AnalyzerMetrics`.
3. Add the analyzer to the registry with a unique name.
4. Test unchanged input twice and compare fingerprints.

```python
class TodoAnalyzer:
    metadata = AnalyzerMetadata(
        name="custom.todo",
        version="1.0.0",
        supported_languages=frozenset({"python"}),
    )

    async def analyze(self, context: AnalyzerContext) -> AnalyzerResult:
        # Read bytes only. Never import or execute repository modules.
        return AnalyzerResult()

registry = AnalyzerRegistry()
registry.register(TodoAnalyzer())
result = await DeterministicAnalyzerOrchestrator(registry).run(context)
```

## Contracts

| Contract | Requirement |
| --- | --- |
| Metadata | Name and version are stable; supported languages and capabilities are explicit. |
| Findings | Use normalized fields and stable fingerprint inputs. |
| Failures | Throwing one analyzer becomes a recorded partial failure. |
| Timeout | The orchestrator isolates each analyzer with its configured timeout. |
| Ordering | Registry execution and combined findings are sorted deterministically. |
| Safety | Repository content is untrusted bytes; no dynamic loading or execution. |
