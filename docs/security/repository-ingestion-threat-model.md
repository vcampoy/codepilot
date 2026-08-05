# Secure repository ingestion threat model

CodePilot treats every repository as hostile input. Prompt 04 validates a public Git HTTPS target, clones it into an isolated temporary workspace, records only bounded metadata, and removes the workspace when the ingestion context exits.

## Quick path

1. Accept an HTTPS URL with no credentials, query, fragment, local path, or non-default port.
2. Resolve every address and reject localhost, private, loopback, link-local, multicast, reserved, and unspecified targets.
3. Pass the validated address set to Git through `http.curloptResolve`, disable redirects, and keep TLS verification enabled.
4. Clone with a Git argument list, shallow history, no tags, no submodules, disabled prompts, disabled system/global configuration, proxy variables removed, and stdout/stderr sent to `DEVNULL`.
5. Enforce timeout, byte, and file-count limits during interval-based monitoring and again after cloning.
6. Bound metadata stdout to 4 KiB, discard metadata stderr, and normalize output overflow to a domain error.
7. Inspect files without importing, compiling, or executing repository content.
8. Use `async with RepositoryIngestionService.ingest(...)` so cleanup is deterministic on success, failure, timeout, and cancellation.

## Assets and trust boundaries

| Asset or boundary | Protection |
| --- | --- |
| Git process and host network | URL validation, DNS address checks pinned into Git/libcurl, HTTPS-only policy, no shell, no prompts, no proxy environment, TLS verification, redirect refusal, bounded command output |
| Host filesystem | Per-ingestion temporary directory, symlink avoidance, size and count limits, deterministic cleanup |
| Application worker | Metadata-only inspection; repository files are never imported or executed |
| Commit identity | `git rev-parse HEAD` is resolved inside the cloned checkout and validated as a full SHA-1 or SHA-256 |
| Analysis metadata | Ignored dependency/vendor/build/generated paths; file count is worktree-only; source size counts recognized language files |

## Threats and controls

| Threat | Control | Residual risk |
| --- | --- | --- |
| SSRF to cloud metadata or private services | HTTPS-only URLs; require every resolved address to be globally routable; explicitly reject CGNAT/shared `100.64.0.0/10`, private, reserved, loopback, link-local, multicast, and unspecified addresses; pass the same validated addresses to Git's curl resolver pin; reject internal hostname suffixes; refuse redirects | The guarantee depends on the deployed Git/libcurl honoring `http.curloptResolve`; DNS/network state can still change outside the process, so enforce outbound egress policy and keep Git patched |
| Shell injection through a repository URL | `asyncio.create_subprocess_exec` receives a fixed argument list; no shell command string is built from input | Git and its dependencies remain part of the trusted runtime surface |
| Credential or prompt abuse | Reject URL credentials; remove all inherited `GIT_*` and proxy controls; set `GIT_TERMINAL_PROMPT=0`; disable system/global Git configuration; force TLS verification | Git credentials configured outside the process are deployment concerns and must not be mounted into workers |
| History, tag, or submodule expansion | Shallow single-branch clone with no tags and `--no-recurse-submodules` | A single reachable commit can still be large; byte monitoring remains mandatory |
| Disk or metadata exhaustion | Stream directory entries with `os.scandir`; stop at the first byte/file-count violation; use the configured monitor interval; count all non-`.git` files for limits and repeat checks after clone | Monitoring is interval-based and cannot prevent bytes written between scans; OS/container quotas remain mandatory defense in depth |
| Git output exhaustion | Clone output goes to `DEVNULL`; metadata stdout is read in 1 KiB chunks with a 4 KiB cap and stderr is discarded | Git/libc/kernel buffers still exist; OS/container limits and the strict command timeout remain required |
| Repository hooks or source-code execution | Ingestion only invokes Git and reads file metadata/bytes; it never runs project tooling | Later analyzers must preserve this boundary and use dedicated sandboxes for any required execution |
| Symlink escape | Do not follow directory or file symlinks during inspection | Git configuration and later analysis stages must not re-enable symlink traversal implicitly |
| Timeout, cancellation, or cleanup failure | POSIX process groups and Windows process trees are terminated; clone and metadata cancellation events are observed; final waits are bounded; traversal, output, and process failures become explicit domain errors; workspace cleanup retries read-only files | An external process with an open handle can still delay deletion; monitor and alert on cleanup errors |

## Explicitly out of scope

- Private repositories and GitHub OAuth.
- SSH, plain HTTP, `file://`, local paths, or arbitrary Git transports.
- Repository builds, dependency installation, package-manager execution, and analyzer execution.
- Authentication, authorization, persistence, and asynchronous job orchestration.

## Verification checklist

- [x] Local temporary Git repositories cover cloning, commit SHA, branch, language, file count, source size, ignore rules, and cleanup; cleanup assertions observe directories created through the production factory.
- [x] Unsupported schemes and private/internal targets have focused rejection tests.
- [x] Real `SubprocessGitClient` tests cover pinned clone arguments, redirect refusal, inherited Git-control removal, clone timeout/cancellation, process-tree termination, metadata timeout/cancellation, metadata output bounds, metadata failure, and SHA-256.
- [x] CGNAT/shared and other non-public address rejection, service-level metadata cancellation, output/resource behavior, and traversal `RecursionError`/permission failures have regression coverage.
- [x] Timeout, cancellation, byte, file-count, metadata, output, traversal, workspace, cleanup, and process-termination failures have explicit domain errors and cleanup paths.
- [x] Ruff, Mypy, focused pytest, full pytest, and `git diff --check` are required gates for this module.
