"""GitHub App based pull-request publisher."""

from __future__ import annotations

from urllib.parse import urlsplit

from codepilot.github.client import GitHubApiError, GitHubAppAuthenticator, GitHubClient
from codepilot.services.repair import PullRequestPublisher, validate_unified_patch


class GitHubAppPullRequestPublisher(PullRequestPublisher):
    def __init__(
        self,
        client: GitHubClient,
        authenticator: GitHubAppAuthenticator,
        installation_token: str,
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
    ) -> str:
        paths = validate_unified_patch(patch)
        del paths  # validated before any external mutation
        parsed = urlsplit(repository_url)
        if parsed.hostname not in {"github.com", "www.github.com"}:
            raise GitHubApiError("Only GitHub repositories are supported.")
        repository = parsed.path.strip("/").removesuffix(".git")
        if repository.count("/") != 1:
            raise GitHubApiError("Repository URL is invalid.")
        return await self._client.publish_patch(
            repository,
            base_sha=commit_sha,
            branch=branch_name,
            patch=patch,
            title=title,
            body=description,
            token=self._installation_token,
        )
