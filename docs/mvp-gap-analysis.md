# Public MVP gap analysis

## Implemented baseline

- Public HTTPS repository ingestion with SSRF and resource limits.
- PostgreSQL-backed asynchronous analysis state with Celery, leases, retries, and idempotent findings.
- Deterministic analyzer contracts, Python/multilanguage adapters, Git history, dependency graph, risk score, and quality gates.
- React dashboard with typed API calls, polling, responsive empty states, and optional evidence-cited AI output.
- GitHub App boundary with signed idempotent webhooks, rate-limit-aware transport, PR comparison, and concise Check payloads.
- API-key/workspace isolation, in-process rate limiting and quotas, security headers, non-root backend containers, health probes, and CI checks.

## Deliberately incomplete

- Authentication is a minimal deployment API key, not accounts, OAuth, refresh tokens, or a user-management system.
- Rate limits, quotas, and webhook replay storage are in-process; a multi-instance deployment needs Redis/PostgreSQL-backed stores.
- Readiness currently validates application configuration but does not actively probe every database and Redis dependency.
- GitHub webhook dispatch is an adapter boundary; production must connect it to the analysis orchestration workflow and persist installation metadata safely.
- The dashboard has evidence-pending states for findings, hotspots, file detail, graph, and quality-gate endpoints not yet exposed by the current API.
- OpenTelemetry and Sentry are optional integrations and require deployment-specific exporters/DSNs.
- Performance coverage is a deterministic medium-repository benchmark target, not a production capacity guarantee.

These limitations mean the repository is suitable for local development and a controlled MVP pilot, not an unconditional production-readiness claim.
