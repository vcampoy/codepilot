# Security policy

## Supported versions

Only the default branch is currently supported while CodePilot is an MVP.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Contact the maintainers privately with a concise description, reproduction steps, affected commit, and impact. Do not include real credentials or private repository content in the report.

## Security baseline

Repository ingestion enforces HTTPS, SSRF protections, bounded resources, timeouts, and process cleanup. The public API supports a configured API key and workspace header, signed GitHub webhooks, bounded rate limits, and workspace-scoped analysis reads. Optional LLM and error-reporting integrations are disabled unless explicitly configured.
