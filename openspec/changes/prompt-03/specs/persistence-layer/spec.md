# Persistence Layer Specification

## Purpose

Define durable PostgreSQL records, lifecycle invariants, atomicity, and reversible schema evolution.

## Requirements

### Requirement: Persistent records and vocabularies

The system MUST persist the following data with UUID identifiers and UTC timestamps. Required text MUST be non-empty; optional values MAY be null.

| Record | Required data | Optional data |
| --- | --- | --- |
| Repository | `id`, `name`, `provider`, `clone_url`, `default_branch`, `visibility`, `created_at`, `updated_at` | — |
| Analysis | `id`, `repository_id`, `requested_ref`, `status`, `created_at` | `resolved_commit_sha`, `failure_code`, `failure_message`, `started_at`, `completed_at`, `analyzer_version` |
| Finding | `id`, `analysis_id`, `analyzer`, `rule_id`, `severity`, `title`, `description`, `file_path`, `evidence`, `remediation`, `fingerprint` | `line`, `column` |

Allowed values MUST be provider `github|gitlab|bitbucket|other`, visibility `public|private`, analysis status `queued|running|completed|failed`, and severity `info|low|medium|high|critical`. Finding `line` and `column`, when present, MUST be positive integers; `evidence` and `remediation` MUST be JSON objects.

#### Scenario: Values round-trip through storage

- GIVEN valid records using allowed enums and UTC timestamps
- WHEN the records are persisted and retrieved
- THEN all values and UTC instants MUST be preserved

#### Scenario: Invalid persistent value is rejected

- GIVEN an unknown enum value, empty required text, or non-positive location
- WHEN persistence is attempted
- THEN the record MUST NOT be stored

### Requirement: Analysis lifecycle

An analysis MUST begin as `queued`. The only valid transitions SHALL be `queued -> running`, `queued -> failed`, `running -> completed`, and `running -> failed`. Terminal states MUST NOT transition. Entering `running` MUST set `started_at`; entering `completed` or `failed` MUST set `completed_at`. Completed analyses MUST have no failure data; failed analyses MUST have non-empty `failure_code` and `failure_message` values that expose no credentials, tokens, or source content. A queued failure MAY have no `started_at`.

#### Scenario: Analysis completes

- GIVEN a queued analysis
- WHEN it transitions to running and then completed
- THEN both timestamps MUST be UTC and failure data MUST remain null

#### Scenario: Invalid transition is atomic

- GIVEN an analysis whose requested transition is not allowed
- WHEN the transition is attempted
- THEN `invalid_analysis_transition` MUST be reported and no analysis fields MUST change

### Requirement: Relational integrity and access indexes

The system MUST enforce exact uniqueness of repository `(provider, clone_url)` and finding `(analysis_id, fingerprint)`. Foreign keys MUST be indexed and MUST cascade repository deletion to analyses and analysis deletion to findings. Query indexes MUST cover repository `created_at`; analysis `(repository_id, created_at)` and `(status, created_at)`; and finding `(analysis_id, severity)` and `(analysis_id, file_path)`.

#### Scenario: Duplicate deterministic data is rejected

- GIVEN an existing unique key
- WHEN another record repeats that key
- THEN storage MUST reject it without altering the existing record

#### Scenario: Ownership is enforced

- GIVEN stored repository, analysis, and finding records
- WHEN a parent is removed or a nonexistent parent is referenced
- THEN descendants MUST cascade on removal and orphan creation MUST fail

### Requirement: Transaction and resource lifecycle

Database operations MUST be asynchronous. Each request or task MUST use an isolated unit of work that commits all changes or rolls them back on failure. Resources MUST be released afterward and at application shutdown. Committed records MUST survive restarts.

#### Scenario: Multi-write operation fails

- GIVEN an operation has staged multiple writes
- WHEN any write or validation fails before completion
- THEN none of the operation's writes MUST remain committed

### Requirement: Reversible migrations and test isolation

From `backend/`, `alembic upgrade head` MUST create the declared schema on clean PostgreSQL; downgrade to `base` and re-upgrade MUST succeed. Migrations MUST use the runtime secret URL, accept `postgresql://` and `postgresql+asyncpg://`, and MUST NOT persist credentials. PostgreSQL tests MUST migrate clean storage, isolate data, and run in CI.

#### Scenario: Clean schema lifecycle

- GIVEN an empty PostgreSQL database and runtime credentials
- WHEN the schema is upgraded, downgraded, and upgraded again
- THEN every command MUST succeed and the final schema MUST match this specification
