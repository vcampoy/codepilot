# ADR 0001: Deterministic Analysis Before AI

- **Status:** Accepted
- **Date:** 2026-08-03

## Context

CodePilot must produce code intelligence that users can inspect, reproduce, and trust. LLM output can vary by model, provider, prompt, and invocation; it can also be unavailable because of cost, privacy, configuration, or network constraints. Treating that output as authoritative would make findings and quality decisions difficult to verify.

## Decision

Deterministic analysis is CodePilot's source of truth.

- Findings, metrics, graphs, hotspots, risk components, and quality-gate results originate from deterministic tools and versioned CodePilot logic.
- AI is optional and disabled unless configured.
- AI may explain stored evidence, summarize findings, or help prioritize remediation. It may not create or alter authoritative evidence, scores, or gate outcomes.
- AI output must be labeled as generated and traceable to the deterministic evidence supplied to it.
- The platform must remain useful without an LLM or provider credentials.

## Consequences

- Users can reproduce and audit product results independently of an AI provider.
- Core analysis, APIs, tests, and the dashboard cannot require LLM availability.
- AI integrations need an explicit gateway, bounded evidence inputs, validation, privacy controls, and graceful disabled/failure behavior.
- Some explanations may be less fluent when AI is disabled, but the underlying evidence and decisions remain available.
- Deterministic adapters and evidence models must mature before AI enrichment is added.

## Alternatives Considered

| Alternative | Why not selected |
|---|---|
| Use an LLM as the primary analyzer | Results would be less reproducible, harder to validate, provider-dependent, and unavailable in offline or privacy-constrained environments. |
| Blend deterministic and AI findings into one authoritative set | Users could not reliably distinguish measured evidence from generated interpretation. |
| Exclude AI entirely | This would preserve determinism but give up useful explanation and prioritization capabilities that can remain safely optional. |
