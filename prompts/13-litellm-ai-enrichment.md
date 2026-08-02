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

# Prompt 13 — Optional AI enrichment through LiteLLM

## Goal

Add AI-generated explanations and refactoring prioritization without allowing LLM output to become the source of truth.

## Architecture

```text
Application service
  -> internal LlmGateway
  -> LiteLLM adapter
  -> OpenRouter or another configured provider
```

No application code outside the LLM adapter may call LiteLLM directly.

## Initial AI features

1. Explain why a file is high risk.
2. Produce a prioritized repository refactoring plan.
3. Summarize the main deterministic findings.

## Tasks

1. Define typed LLM request and response contracts.
2. Implement:
   - disabled/no-op mode
   - LiteLLM adapter
3. Configure models by task.
4. Validate structured outputs with Pydantic.
5. Add:
   - timeouts
   - retries for transient provider errors
   - fallback models
   - maximum token budgets
   - cost tracking
   - latency tracking
6. Build prompts exclusively from stored deterministic evidence.
7. Add repository-content prompt-injection defenses.
8. Clearly label AI-generated text in the API and frontend.
9. Cache by:
   - analysis
   - task
   - model
   - prompt version
10. Add mocked tests; CI must not call external LLM APIs.
11. Document privacy implications and provider configuration.

## Constraints

- AI must remain disabled by default.
- Never send an entire repository when summarized evidence is sufficient.
- Do not send secrets or files detected as sensitive.
- Do not automatically apply generated code changes.
- AI explanations must cite finding IDs or score components.

## Acceptance criteria

- The complete deterministic product works without an API key.
- AI responses are traceable to stored evidence.
- Invalid structured output is handled safely.
- Cost and token usage are persisted or logged appropriately.
- CI performs no paid network calls.
- Tests, Ruff and Mypy pass.
