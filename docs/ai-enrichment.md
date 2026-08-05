# Optional AI enrichment

CodePilot keeps deterministic analysis as the source of truth. AI enrichment is disabled by default and is never required to queue, run, or inspect an analysis.

## Enablement

Install the optional backend dependency:

```bash
cd backend
python -m pip install -e ".[llm]"
```

Set `LLM_ENABLED=true`, `LLM_PROVIDER`, `LLM_MODEL`, and `LLM_API_KEY`. Optional comma-separated fallback models are configured with `LLM_FALLBACK_MODELS`. Timeouts and response budgets use `LLM_TIMEOUT_SECONDS` and `LLM_MAX_TOKENS`.

The API exposes `POST /api/v1/analyses/{analysis_id}/enrichment/{task}` for `file-risk`, `refactoring-plan`, and `deterministic-summary`. Responses carry `ai_generated`, model/provider metadata, and evidence citations. The no-op gateway returns `enabled=false` when AI is disabled.

## Safety and privacy

- The gateway accepts persisted deterministic evidence, not repository workspaces or arbitrary frontend text.
- Evidence is bounded, secrets are redacted, and instruction-like text is treated as untrusted data.
- Structured provider output is validated with Pydantic and rejected when citations do not match stored evidence IDs or score components.
- Retries are limited to transient failures; fallback models do not bypass validation.
- Usage, cost, latency, and cache identity are recorded through the metrics sink. Replace the in-memory sink with a durable implementation when operational persistence is introduced.
- Tests inject a provider stub and never call paid external models.

Generated text is explanatory only. Code changes are never applied automatically.
