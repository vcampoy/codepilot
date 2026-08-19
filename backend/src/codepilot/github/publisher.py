"""GitHub App based pull-request publisher."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from codepilot.github.client import GitHubApiError, GitHubAppAuthenticator, GitHubClient
from codepilot.services.repair import PullRequestPublisher, validate_unified_patch


class GitHubAppPullRequestPublisher(PullRequestPublisher):
    def __init__(
        self,
        client: GitHubClient,
        authenticator: GitHubAppAuthenticator,
        installation_token: str | None = None,
    ):
        self._client = client
        self._authenticator = authenticator
        self._installation_token = installation_token

    async def publish(
        self,
        repository_url: str,
        commit_sha: str,
        branch_name: str,
        patch: str,
        title: str,
        description: str,
        base_branch: str | None = None,
    ) -> str:
        paths = validate_unified_patch(patch)
        del paths  # validated before any external mutation
        parsed = urlsplit(repository_url)
        if parsed.hostname not in {"github.com", "www.github.com"}:
            raise GitHubApiError("Only GitHub repositories are supported.")
        repository = parsed.path.strip("/").removesuffix(".git")
        if repository.count("/") != 1:
            raise GitHubApiError("Repository URL is invalid.")
        files = await asyncio.to_thread(_materialize_patch, repository_url, commit_sha, patch)
        token = self._installation_token
        if token is None:
            app_token = self._authenticator.create_app_token()
            installation = await self._client.repository_installation(repository, token=app_token)
            token = await self._client.create_installation_token(installation, app_token)
        return await self._client.publish_files(
            repository,
            base_sha=commit_sha,
            branch=branch_name,
            files=files,
            title=title,
            body=description,
            base_branch=base_branch,
            token=token,
        )


def _materialize_patch(repository_url: str, commit_sha: str, patch: str) -> dict[str, str | None]:
    root = Path(tempfile.mkdtemp(prefix="codepilot-publish-"))
    try:
        checkout = root / "repo"
        _run(("git", "clone", "--no-checkout", repository_url, str(checkout)), root)
        _run(("git", "checkout", "--detach", commit_sha), checkout)
        patch_file = root / "change.patch"
        patch_file.write_text(patch, encoding="utf-8")
        _run(("git", "apply", "--whitespace=nowarn", str(patch_file)), checkout)
        names = _run(("git", "diff", "--name-status", commit_sha), checkout).splitlines()
        files: dict[str, str | None] = {}
        for item in names:
            status, _, path = item.partition("\t")
            if not path or status.startswith("R") or status.startswith("C"):
                raise GitHubApiError("Rename patches are not supported.")
            files[path] = (
                None if status.startswith("D") else (checkout / path).read_text(encoding="utf-8")
            )
        return files
    except (OSError, subprocess.SubprocessError) as error:
        raise GitHubApiError("Repair patch could not be materialized.") from error
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _run(command: tuple[str, ...], cwd: Path) -> str:
    result = subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, check=False, timeout=120
    )
    if result.returncode != 0:
        raise subprocess.SubprocessError(result.stderr[-500:])
    return result.stdout
