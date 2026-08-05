# GitHub App integration

CodePilot's GitHub boundary uses a GitHub App, not a personal access token. The adapter creates short-lived App JWTs, exchanges them for installation tokens, discovers installation repositories, reads pull-request diffs, and publishes one concise Check Run. Installation tokens are held only for the request that uses them; no token is logged or persisted by this phase.

## Minimum permissions

Request only:

- **Metadata: Read-only** — discover repositories and installation metadata.
- **Contents: Read-only** — inspect the repository snapshot and pull-request diff.
- **Checks: Read and write** — publish the CodePilot Check Run.

Pull requests are read-only. CodePilot does not post inline comments by default.

## Configuration

Install the optional adapter dependencies with `python -m pip install -e ".[github]"`, then configure `GITHUB_ENABLED`, `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`, and the API URL. Keep private keys and webhook secrets in the deployment secret manager; never commit them.

## Local webhook development

Expose the local API with a tunnel such as `cloudflared tunnel --url http://localhost:8000`, configure the GitHub App webhook URL as `/api/v1/github/webhook`, and select `push` and `pull_request` events. The endpoint verifies `X-Hub-Signature-256`, normalizes supported `opened`, `synchronize`, and `reopened` pull-request actions, and claims `X-GitHub-Delivery` before dispatch. Replayed deliveries are acknowledged without a second dispatch.

Pull-request comparison is diff-focused: it reports new and resolved deterministic findings, risk delta, new hotspots, and the quality-gate result. GitHub API calls use bounded rate-limit backoff. No repository content is sent to an LLM by this integration; the optional AI boundary remains separately configured and disabled by default.
