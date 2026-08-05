# ADR 0002: Public MVP hardening boundaries

## Status

Accepted

## Decision

The public MVP uses a minimal API-key authentication flow with a bounded workspace identifier, PostgreSQL workspace ownership on analyses, and an in-process sliding-window limiter/quota. External LLM, GitHub, telemetry, and error-reporting integrations remain opt-in adapters. Application containers run as non-root where practical and drop Linux capabilities in Compose.

## Rationale

This protects the primary tenant-owned analysis path without introducing enterprise identity infrastructure before the product validates its workflow. PostgreSQL is the durable ownership source; in-process limits are intentionally acceptable only for a single-instance pilot and are called out in the gap analysis.

## Consequences

- Production must set `AUTH_REQUIRED=true` and a secret `AUTH_API_KEY`.
- Every tenant-owned analysis read is filtered by workspace ID; a foreign workspace receives the same not-found response as an unknown analysis.
- Multi-instance deployments must replace in-process rate, quota, and webhook replay state with shared stores.
- Optional integrations cannot make deterministic analysis unavailable when disabled or unconfigured.
