# Repository Analysis API Specification

## Purpose

Define repository and nested-analysis creation and listing without future-phase behavior.

## Requirements

### Requirement: Create a repository

`POST /api/v1/repositories` MUST require exactly `name`, `provider`, `clone_url`, `default_branch`, and `visibility`. Text MUST equal its trimmed form. `name` and `default_branch` MUST be 1–255 characters; `clone_url` MUST be 1–2048, opaque, and exact. URL security and canonicalization are deferred. Enums MUST use persistence vocabularies.

Success MUST atomically persist one repository and return `201` with exactly `id`, request fields, and UTC `created_at` and `updated_at`.

#### Scenario: Repository is created

- GIVEN a valid body with a unique exact `(provider, clone_url)`
- WHEN the client creates a repository
- THEN the API MUST return `201` and the persisted repository representation

#### Scenario: Repository already exists

- GIVEN the exact provider and clone URL already exist
- WHEN the client creates the repository, including during a concurrent race
- THEN the API MUST return `409`, code `repository_already_exists`, message `Repository already exists.`, and no new record

### Requirement: List repositories

`GET /api/v1/repositories` MUST support integer `offset` and `limit`, defaulting to `0` and `20`. Offset MUST be non-negative and limit MUST be 1–100. The response MUST be `{items,total,offset,limit}`; `total` counts all repositories. Items MUST use create-response fields and order by `created_at`, then `id`, both ascending.

#### Scenario: Repository page is stable

- GIVEN repositories sharing a creation timestamp
- WHEN the same valid page is requested without intervening writes
- THEN `200` MUST return the same ordered items, total, offset, and limit

#### Scenario: Repository page is empty

- GIVEN an offset at or beyond the total
- WHEN the page is requested
- THEN `items` MUST be empty while `total`, `offset`, and `limit` remain accurate

### Requirement: Create a nested analysis

`POST /api/v1/repositories/{repository_id}/analyses` MUST require only `requested_ref`, equal to its trimmed form and 1–255 characters long. Success MUST atomically persist a `queued` analysis for that repository and return `201` with exactly `id`, `repository_id`, `requested_ref`, `status`, `resolved_commit_sha`, `failure_code`, `failure_message`, `started_at`, `completed_at`, `analyzer_version`, and `created_at`. Optional lifecycle fields MUST be null.

Creation MUST NOT validate or resolve the ref, clone source, enqueue work, run an analyzer, or create findings.

#### Scenario: Queued analysis is created

- GIVEN an existing repository and valid requested ref
- WHEN the client creates its analysis
- THEN the API MUST return `201`, status `queued`, null lifecycle fields, and no job side effect

#### Scenario: Analysis parent is missing

- GIVEN a well-formed UUID that identifies no repository
- WHEN the client creates a nested analysis
- THEN the API MUST return `404`, code `repository_not_found`, message `Repository not found.`, and persist nothing

### Requirement: List nested analyses

`GET /api/v1/repositories/{repository_id}/analyses` MUST return only that repository's analyses using the analysis response fields and the same pagination defaults, bounds, envelope, total semantics, and ascending `created_at,id` ordering.

#### Scenario: Nested analysis page is scoped

- GIVEN analyses belonging to multiple repositories
- WHEN one repository's analyses are listed
- THEN `200` MUST include and count only analyses owned by that repository

#### Scenario: Analysis-list parent is missing

- GIVEN a well-formed UUID that identifies no repository
- WHEN its analyses are listed
- THEN the API MUST return `404`, code `repository_not_found`, and message `Repository not found.`

### Requirement: Validation and public errors

Unknown fields, malformed UUIDs, invalid enums, missing fields, invalid strings, and out-of-range pagination MUST return `422`, code `request_validation_error`, and message `Request validation failed.` All errors MUST use `{ "error": { "code", "message", "correlation_id", "details"? } }`; header and body correlation IDs MUST match. ORM or database details MUST NOT be exposed.

This capability MUST NOT add analysis transition/status routes, public finding routes, deletion, provider tokens, source storage, authentication, summaries, retries, or worker behavior.

#### Scenario: Request validation fails safely

- GIVEN an invalid request containing a sensitive submitted value
- WHEN validation fails
- THEN the API MUST return the stable `422` envelope without echoing that value or changing storage
