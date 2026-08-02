# CodePilot Roadmap

This roadmap sequences the work after the Phase 1 foundation. Each phase should deliver a usable, verifiable capability without implementing later phases prematurely. Exit criteria describe evidence of completion, not a commitment to a specific internal design beyond the constraints already established.

## Delivery Principles

- Deterministic evidence remains authoritative; AI is optional enrichment.
- Security boundaries are designed before untrusted repository content enters the system.
- Each phase preserves a runnable repository and adds tests for its new contracts.
- Product claims remain bounded by collected evidence and supported languages.
- Later implementation choices stay open unless an earlier contract requires them.

## Phase Overview

| Phase | Outcome |
|---|---|
| 2 | Reliable configuration, logging, correlation, and API errors |
| 3 | Durable PostgreSQL persistence and migrations |
| 4 | Safe ingestion of public Git repositories |
| 5 | Idempotent asynchronous analysis orchestration |
| 6 | Deterministic analyzer framework and generic metrics |
| 7 | Python static-analysis adapters |
| 8 | JavaScript/TypeScript and .NET/SARIF adapters |
| 9 | Git history metrics and explainable hotspots |
| 10 | Dependency graphs and evidence-backed architecture insights |
| 11 | Explainable risk scoring and configurable quality gates |
| 12 | Focused MVP dashboard |
| 13 | Optional LiteLLM-based explanation and prioritization |
| 14 | GitHub App integration and pull-request analysis |
| 15 | Public MVP hardening and release readiness |

## Phase 2: Configuration, Logging, And Errors

**Goal:** Establish predictable runtime configuration, structured observability, request correlation, and a safe API error contract.

**Key deliverables**

- [ ] Typed settings cover environment, PostgreSQL, Redis/Celery, logging, CORS, analysis limits, and optional LLM configuration.
- [ ] Startup rejects missing, dangerous, or inconsistent production settings without exposing secrets.
- [ ] Structured logs carry request correlation, method, path, status, and duration in local and container environments.
- [ ] Correlation IDs are validated or generated, returned to clients, and propagated through logs.
- [ ] Central exception handling maps validation, expected application, and unexpected failures to a stable safe response format.
- [ ] Configuration, redaction, correlation, and error behavior are documented and tested.

**Exit criteria**

- [ ] Invalid required configuration fails early with an actionable message.
- [ ] Every API response and request log can be correlated without leaking secrets or stack traces.
- [ ] Expected and unexpected failures follow the documented contract, and backend quality checks pass.

## Phase 3: Persistence And Alembic

**Goal:** Make repository, analysis, and finding state durable in PostgreSQL with controlled schema evolution.

**Key deliverables**

- [ ] Minimum domain and persistence models exist for repositories, analyses, and deterministic findings.
- [ ] Async database sessions and transaction ownership are explicit and testable.
- [ ] Repository contracts separate application behavior from database-specific models.
- [ ] Alembic can create and evolve the schema from a clean database.
- [ ] API operations persist repositories and analyses and expose bounded, paginated lists.
- [ ] Constraints, indexes, timezone-aware timestamps, fingerprints, and analysis state transitions are defined deliberately.

**Exit criteria**

- [ ] A clean database reaches the current schema through migrations alone.
- [ ] Records survive process restarts, relationships are enforced, and invalid status transitions are rejected.
- [ ] Database integration tests are isolated and all backend quality checks pass.

## Phase 4: Secure Repository Ingestion

**Goal:** Safely obtain and inspect public Git repositories without trusting or executing their contents.

**Key deliverables**

- [ ] Public HTTPS Git URLs are validated while local paths, file URLs, localhost, and private network targets are rejected.
- [ ] Cloning runs in isolated temporary storage with bounded time, repository size, and file count.
- [ ] Cleanup is guaranteed across success, failure, timeout, and cancellation paths.
- [ ] Ingestion resolves the analyzed commit and records bounded repository metadata such as languages, source size, and file count.
- [ ] Ignore rules exclude version control data, dependencies, vendors, build outputs, and detectable generated content.
- [ ] A documented threat model and explicit safe ingestion failures are covered with local Git fixtures.

**Exit criteria**

- [ ] A supported public repository can be cloned, inspected, and tied to a persisted commit SHA.
- [ ] SSRF defenses and all configured resource limits have regression tests.
- [ ] Untrusted code is never executed, temporary resources are removed, and backend quality checks pass.

## Phase 5: Asynchronous Orchestration

**Goal:** Run analyses through a robust, observable, and idempotent background workflow.

**Key deliverables**

- [ ] An application service accepts analysis requests, persists initial state, and enqueues background work.
- [ ] Worker orchestration covers ingestion, analyzer execution, finding persistence, summary calculation, and terminal state updates.
- [ ] Queued, running, completed, and failed transitions are explicit; cancellation is included only if it can be supported coherently.
- [ ] Duplicate delivery and safe retries do not duplicate findings or corrupt state.
- [ ] Retry policy distinguishes transient failures from permanent failures and separates internal detail from client-safe messages.
- [ ] Status and summary APIs expose file, source-line, severity, duration, and failure information from PostgreSQL.

**Exit criteria**

- [ ] Analysis requests return an accepted response with a durable analysis identifier.
- [ ] Duplicate task execution produces one consistent persisted result, and failures remain observable.
- [ ] Redis carries orchestration messages rather than repository contents or authoritative product state, and worker integration checks pass.

## Phase 6: Analyzer Framework And Generic Metrics

**Goal:** Create the deterministic, language-aware contract used by all analyzer implementations.

**Key deliverables**

- [ ] Contracts define analyzer identity, version, capabilities, execution context, normalized findings, metrics, and failures.
- [ ] A registry selects supported analyzers without loading arbitrary third-party code.
- [ ] Normalized findings preserve category, severity, location, evidence, remediation metadata, and stable fingerprint inputs.
- [ ] Generic analyzers report basic file/language metrics and deterministic large-file and long-line findings.
- [ ] Analyzer timeouts and partial failures are represented without automatically invalidating every successful result.
- [ ] Contributor guidance demonstrates how to add and test an analyzer.

**Exit criteria**

- [ ] Registered analyzers run through one orchestration contract and report execution metadata.
- [ ] Repeated analysis of unchanged content produces the same normalized findings and fingerprints regardless of analyzer order.
- [ ] Exclusions, timeout behavior, partial failures, and generic analyzers are comprehensively tested.

## Phase 7: Python Analysis Adapters

**Goal:** Provide credible Python analysis by adapting established deterministic tools to CodePilot's analyzer contract.

**Key deliverables**

- [ ] Ruff, Bandit, and Radon adapters use machine-readable output where technically compatible.
- [ ] Tool findings and metrics are normalized without losing original rule identifiers or provenance.
- [ ] Severity/category mappings, tool versions, execution duration, and supported metrics are documented.
- [ ] Secure defaults avoid importing or executing target modules, tests, or application code.
- [ ] Missing tools, unsupported syntax, malformed output, and timeouts produce explicit availability or failure states.
- [ ] Representative Python fixtures cover parsing, locations, metrics, normalization, and fingerprint stability.

**Exit criteria**

- [ ] A fixture repository produces correctly located, normalized results from the available Python tools.
- [ ] External-tool findings are distinguishable from CodePilot-derived logic, with tested severity mappings.
- [ ] Tool absence degrades explicitly rather than crashing the complete analysis, and backend quality checks pass.

## Phase 8: JavaScript, TypeScript, And .NET Adapters

**Goal:** Prove the analyzer architecture is language-neutral through ESLint and safe SARIF 2.1 ingestion, including Roslyn-originated results.

**Key deliverables**

- [ ] ESLint JSON results are adapted to normalized CodePilot findings without installing dependencies in untrusted repositories.
- [ ] A bounded SARIF 2.1 importer handles rules, levels, locations, fingerprints, and provenance.
- [ ] Existing SARIF artifacts can be imported through a size- and structure-validated contract.
- [ ] Roslyn or `dotnet` analyzer output is supported through SARIF; local execution remains optional and only uses a demonstrably safe mode.
- [ ] Analyzer availability reports whether each integration ran, skipped, or failed.
- [ ] JavaScript/TypeScript fixtures, .NET fixtures, and malformed SARIF samples exercise parsing and safety limits.

**Exit criteria**

- [ ] ESLint and Roslyn SARIF samples normalize consistently with correct paths and rule provenance.
- [ ] Oversized, malformed, or excessively nested artifacts are rejected safely.
- [ ] No workflow runs arbitrary install scripts or build targets from a target repository, and backend quality checks pass.

## Phase 9: Git History And Hotspots

**Goal:** Combine bounded Git history signals with code evidence to identify frequently changed, difficult areas.

**Key deliverables**

- [ ] Git-native history analysis calculates commit frequency, recency, author count, ownership concentration, file age, and churn without GitHub APIs.
- [ ] Configurable time and traversal limits keep large histories bounded.
- [ ] File history is rename-aware where evidence can be resolved reliably, with limitations documented.
- [ ] Per-file history metrics are persisted for each analysis.
- [ ] An explainable hotspot model combines complexity or finding density with recent churn.
- [ ] APIs expose ranked hotspots, component metrics, and score explanations without framing author data as individual performance.

**Exit criteria**

- [ ] Generated Git histories produce expected deterministic metrics.
- [ ] Frequently changed, high-complexity files rank above stable files for documented reasons.
- [ ] Every hotspot exposes its components, configured bounds are respected, and backend quality checks pass.

## Phase 10: Dependency Graph And Architecture Insights

**Goal:** Add bounded structural intelligence for Python, JavaScript/TypeScript, and C# without claiming complete semantic understanding.

**Key deliverables**

- [ ] Graph contracts capture nodes, edges, their types, and extraction provenance.
- [ ] Language-specific extractors identify imports or references without requiring successful project compilation.
- [ ] Module/file graphs calculate bounded degree metrics, strongly connected components, cycles, coupling indicators, and meaningful isolation.
- [ ] Persistence retains useful summaries while avoiding unbounded raw graph storage.
- [ ] Paginated or otherwise bounded APIs support graph consumers.
- [ ] Architecture findings such as cycles or excessive fan-in/fan-out link directly to supporting graph edges and caveats.

**Exit criteria**

- [ ] Fixtures generate expected nodes, edges, cycles, and graph metrics.
- [ ] Every architecture finding is reproducible from exposed evidence and avoids unsupported framework claims.
- [ ] Large inputs remain within configured storage, processing, and response bounds.

## Phase 11: Explainable Risk And Quality Gates

**Goal:** Produce a transparent, versioned risk model and configurable gates focused on newly introduced problems.

**Key deliverables**

- [ ] Risk configuration versions normalized components, weights, thresholds, and edge-case behavior.
- [ ] File and repository risk use only available evidence such as complexity, churn, finding severity/density, coupling, ownership concentration, and supplied coverage.
- [ ] Stored results retain the final score, model version, component values, and effective weights.
- [ ] Risk categories communicate useful ranges without implying scientific certainty or fake precision.
- [ ] Baseline comparison separates existing findings, resolved findings, and newly introduced risk.
- [ ] Quality gates evaluate explicit criteria such as new critical findings, risk, and hotspots, with debt estimates only if defensible data exists.

**Exit criteria**

- [ ] Every displayed score can be reconstructed from stored components and documented configuration.
- [ ] Boundary and weight changes produce predictable tested results.
- [ ] Every gate result names the evidence and reason for passing or failing, especially for newly introduced problems.

## Phase 12: MVP Dashboard

**Goal:** Turn the available backend evidence into a focused, accessible workflow for submitting and understanding analyses.

**Key deliverables**

- [ ] Users can list and submit public repositories, inspect repository details, and follow analysis history and status.
- [ ] Analysis views present overview metrics, analyzer status, findings, hotspots, file-level score breakdowns, and quality-gate results.
- [ ] A bounded dependency graph communicates structural evidence without overwhelming the browser or the user.
- [ ] Routing, typed API contracts, and server-state behavior support clear loading, empty, progress, and error states.
- [ ] Forms, filters, and tables are accessible and responsive across supported screen sizes.
- [ ] Critical user flows have frontend tests, with no fake production data or provider secrets.

**Exit criteria**

- [ ] A user can submit a repository and follow it from request through completed or failed analysis.
- [ ] Completed analyses expose readable evidence, scores, hotspots, findings, and graph context.
- [ ] API failures are actionable, and frontend build, type, lint, and test checks pass.

## Phase 13: Optional LiteLLM Enrichment

**Goal:** Add optional AI explanations and prioritization while deterministic evidence remains authoritative and fully usable on its own.

**Key deliverables**

- [ ] An internal LLM gateway isolates provider access, with disabled/no-op behavior and a LiteLLM adapter.
- [ ] Typed, validated contracts cover evidence-based risk explanations, finding summaries, and refactoring prioritization.
- [ ] Task-level model configuration supports bounded tokens, timeouts, transient retries, fallback behavior, and cost/latency accounting.
- [ ] Prompts use the minimum necessary stored evidence, defend against repository prompt injection, and exclude detected secrets or sensitive content.
- [ ] Generated content is labeled and cites finding identifiers or score components.
- [ ] Cache identity includes analysis, task, model, and prompt version; CI uses mocks and never makes paid provider calls.

**Exit criteria**

- [ ] All deterministic product flows work with AI disabled and no provider credentials.
- [ ] AI output is validated, safely failure-tolerant, and traceable to stored evidence.
- [ ] Privacy behavior, provider configuration, token/cost handling, and limitations are documented and tested.

## Phase 14: GitHub App And Pull-Request Analysis

**Goal:** Let installed GitHub users discover repositories and receive focused, evidence-backed pull-request checks.

**Key deliverables**

- [ ] A least-privilege GitHub App flow manages installation metadata and any required credentials safely.
- [ ] Repository discovery is scoped to installed accounts and delegated through a dedicated GitHub adapter.
- [ ] Signed webhooks support relevant push and pull-request lifecycle events with replay-safe idempotency.
- [ ] Pull-request analysis compares against a baseline to identify new/resolved findings, risk delta, new hotspots, and gate results.
- [ ] A concise GitHub Check links to the full CodePilot analysis without noisy inline comments by default.
- [ ] Rate limits, backoff, secret redaction, mocked integration tests, local webhook guidance, and permission documentation are in place.

**Exit criteria**

- [ ] Invalid signatures are rejected and replayed deliveries cannot trigger duplicate analyses.
- [ ] A pull-request fixture produces a deterministic baseline comparison and explicit quality-gate outcome.
- [ ] GitHub output is concise, traceable, least-privilege, and no integration secret appears in logs.

## Phase 15: Public MVP Hardening

**Goal:** Prepare a credible limited public release with evidence-based security, reliability, operations, and documentation.

**Key deliverables**

- [ ] A repository-wide audit identifies release blockers and produces an honest MVP gap analysis.
- [ ] Minimal authentication, workspace ownership, and authorization prevent cross-tenant resource access.
- [ ] Rate, repository, analysis, upload, and concurrency limits protect public endpoints and workers.
- [ ] Security hardening covers secret redaction, safe headers, dependency scanning, container/runtime posture, and SSRF regressions.
- [ ] Operational visibility includes health/readiness/liveness, OpenTelemetry instrumentation, and configurable error reporting.
- [ ] End-to-end and integration coverage proves the primary user flow; representative performance tests establish bounded behavior.
- [ ] Contributor, security, architecture, deployment, and local-development documentation supports another engineer without hidden knowledge.
- [ ] CI, release checks, demo material, licensing, and community files are reviewed for public release quality.

**Exit criteria**

- [ ] The primary user flow is automated and passing from repository submission or connection through analysis results and pull-request checks.
- [ ] Tenant isolation, public limits, hardened containers, and critical security regressions have direct test evidence.
- [ ] Deployment and local-development instructions are reproducible, CI is green, and remaining limitations are stated without claiming unsupported production readiness.
