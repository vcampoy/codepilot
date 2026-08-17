"""Dedicated GitHub App adapter with rate-limit-aware HTTP calls."""

from __future__ import annotations

import asyncio
import base64
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from codepilot.github.contracts import GitHubResponse


class GitHubApiError(Exception):
    """Safe GitHub API failure without token or response-body leakage."""


class GitHubRateLimitError(GitHubApiError):
    """The bounded retry budget was exhausted by GitHub rate limiting."""


class GitHubAppAuthenticator:
    """Create short-lived GitHub App JWTs without persisting them."""

    def __init__(
        self,
        *,
        app_id: int,
        private_key: str,
        encode: Callable[[dict[str, object], str, str], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._app_id = app_id
        self._private_key = private_key
        self._encode = encode or _load_jwt_encoder()
        self._clock = clock or (lambda: datetime.now(UTC))

    def create_app_token(self) -> str:
        now = int(self._clock().timestamp())
        claims = {"iat": now - 60, "exp": now + 540, "iss": str(self._app_id)}
        return self._encode(claims, self._private_key, "RS256")


class GitHubRequest(Protocol):
    async def __call__(self, method: str, path: str, **kwargs: object) -> GitHubResponse: ...


class GitHubClient:
    """All external GitHub calls live behind this adapter."""

    def __init__(
        self,
        *,
        request: GitHubRequest | None = None,
        api_base_url: str = "https://api.github.com",
        max_retries: int = 3,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._request_transport = request or _httpx_request(api_base_url)
        self._api_base_url = api_base_url.rstrip("/")
        self._max_retries = max_retries
        self._sleep = sleep

    async def create_installation_token(self, installation_id: int, app_token: str) -> str:
        response = await self._request(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            token=app_token,
        )
        token = response.payload.get("token") if isinstance(response.payload, dict) else None
        if not isinstance(token, str) or not token:
            raise GitHubApiError("GitHub did not return an installation token.")
        return token

    async def list_installation_repositories(
        self, installation_token: str, *, page: int = 1, per_page: int = 100
    ) -> dict[str, Any]:
        response = await self._request(
            "GET",
            f"/installation/repositories?page={page}&per_page={min(per_page, 100)}",
            token=installation_token,
        )
        if not isinstance(response.payload, dict):
            raise GitHubApiError("GitHub returned an invalid repository response.")
        return response.payload

    async def get_pull_diff(self, repository: str, pull_request_number: int, *, token: str) -> str:
        response = await self._request(
            "GET",
            f"/repos/{repository}/pulls/{pull_request_number}",
            token=token,
            accept="application/vnd.github.v3.diff",
        )
        return response.text

    async def create_check_run(
        self,
        repository: str,
        head_sha: str,
        payload: Mapping[str, object],
        *,
        token: str,
    ) -> dict[str, Any]:
        response = await self._request(
            "POST",
            f"/repos/{repository}/check-runs",
            token=token,
            json_payload={**payload, "head_sha": head_sha},
        )
        if not isinstance(response.payload, dict):
            raise GitHubApiError("GitHub returned an invalid check response.")
        return response.payload

    async def repository_installation(self, repository: str, *, token: str) -> int:
        response = await self._request("GET", f"/repos/{repository}/installation", token=token)
        if not isinstance(response.payload, dict) or not isinstance(
            response.payload.get("id"), int
        ):
            raise GitHubApiError("GitHub did not return an installation for the repository.")
        return int(response.payload["id"])

    async def repository_default_branch(self, repository: str, *, token: str) -> str:
        response = await self._request("GET", f"/repos/{repository}", token=token)
        branch = (
            response.payload.get("default_branch") if isinstance(response.payload, dict) else None
        )
        if not isinstance(branch, str) or not branch:
            raise GitHubApiError("GitHub did not return a default branch.")
        return branch

    async def publish_files(
        self,
        repository: str,
        *,
        base_sha: str,
        branch: str,
        files: Mapping[str, str | None],
        title: str,
        body: str,
        base_branch: str | None = None,
        token: str,
    ) -> str:
        if not files:
            raise GitHubApiError("Repair did not produce changed files.")
        base_tree = await self._base_tree(repository, base_sha, token)
        entries = await self._blob_entries(repository, files, token)
        tree_sha = await self._create_tree(repository, base_tree, entries, token)
        commit_sha = await self._create_commit(repository, tree_sha, base_sha, title, token)
        await self._create_ref(repository, branch, commit_sha, token)
        try:
            target_branch = base_branch or await self.repository_default_branch(
                repository, token=token
            )
            response = await self._request(
                "POST",
                f"/repos/{repository}/pulls",
                token=token,
                json_payload={
                    "title": title,
                    "body": body,
                    "head": branch,
                    "base": target_branch,
                },
            )
            url = response.payload.get("html_url") if isinstance(response.payload, dict) else None
            if not isinstance(url, str) or not url:
                raise GitHubApiError("GitHub did not return a pull request URL.")
            return url
        except Exception:
            await self._delete_ref_best_effort(repository, branch, token)
            raise

    async def _base_tree(self, repository: str, commit_sha: str, token: str) -> str:
        response = await self._request(
            "GET", f"/repos/{repository}/git/commits/{commit_sha}", token=token
        )
        tree = response.payload.get("tree", {}) if isinstance(response.payload, dict) else {}
        value = tree.get("sha") if isinstance(tree, dict) else None
        if not isinstance(value, str) or not value:
            raise GitHubApiError("GitHub did not return the base tree.")
        return value

    async def _blob_entries(
        self, repository: str, files: Mapping[str, str | None], token: str
    ) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        for path, content in files.items():
            blob_sha = await self._create_blob(repository, content, token)
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob_sha})
        return entries

    async def _create_blob(self, repository: str, content: str | None, token: str) -> str | None:
        if content is None:
            return None
        response = await self._request(
            "POST",
            f"/repos/{repository}/git/blobs",
            token=token,
            json_payload={
                "content": base64.b64encode(content.encode()).decode(),
                "encoding": "base64",
            },
        )
        value = response.payload.get("sha") if isinstance(response.payload, dict) else None
        if not isinstance(value, str):
            raise GitHubApiError("GitHub did not return a blob SHA.")
        return value

    async def _create_tree(
        self,
        repository: str,
        base_tree: str,
        entries: list[dict[str, object]],
        token: str,
    ) -> str:
        response = await self._request(
            "POST",
            f"/repos/{repository}/git/trees",
            token=token,
            json_payload={"base_tree": base_tree, "tree": entries},
        )
        value = response.payload.get("sha") if isinstance(response.payload, dict) else None
        if not isinstance(value, str):
            raise GitHubApiError("GitHub did not return the repair tree.")
        return value

    async def _create_commit(
        self, repository: str, tree_sha: str, base_sha: str, title: str, token: str
    ) -> str:
        response = await self._request(
            "POST",
            f"/repos/{repository}/git/commits",
            token=token,
            json_payload={"message": title, "tree": tree_sha, "parents": [base_sha]},
        )
        value = response.payload.get("sha") if isinstance(response.payload, dict) else None
        if not isinstance(value, str):
            raise GitHubApiError("GitHub did not return the repair commit.")
        return value

    async def _create_ref(self, repository: str, branch: str, commit_sha: str, token: str) -> None:
        await self._request(
            "POST",
            f"/repos/{repository}/git/refs",
            token=token,
            json_payload={"ref": f"refs/heads/{branch}", "sha": commit_sha},
        )

    async def _delete_ref_best_effort(self, repository: str, branch: str, token: str) -> None:
        try:
            await self._request(
                "DELETE", f"/repos/{repository}/git/refs/heads/{branch}", token=token
            )
        except GitHubApiError:
            return

    async def _request(self, method: str, path: str, **kwargs: object) -> GitHubResponse:
        last_rate_limit = False
        for attempt in range(self._max_retries + 1):
            response = await self._request_transport(method, path, **kwargs)
            if response.status_code in {403, 429}:
                last_rate_limit = True
                if attempt == self._max_retries:
                    break
                await self._sleep(_retry_after(response.headers))
                continue
            if response.status_code >= 400:
                raise GitHubApiError(f"GitHub request failed with HTTP {response.status_code}.")
            return response
        if last_rate_limit:
            raise GitHubRateLimitError("GitHub rate-limit retry budget exhausted.")
        raise GitHubApiError("GitHub request failed.")


def _retry_after(headers: Mapping[str, str]) -> float:
    retry_after = headers.get("Retry-After")
    if retry_after is not None:
        try:
            return min(max(float(retry_after), 0), 60)
        except ValueError:
            pass
    reset = headers.get("X-RateLimit-Reset")
    if reset is not None:
        try:
            return min(max(float(reset) - time.time(), 0), 60)
        except ValueError:
            pass
    return 1.0


def _load_jwt_encoder() -> Callable[[dict[str, object], str, str], str]:
    try:
        import jwt  # type: ignore[import-not-found]
    except ImportError as error:
        raise GitHubApiError(
            "PyJWT is not installed. Install the backend github extra to enable GitHub App auth."
        ) from error
    return cast(Callable[[dict[str, object], str, str], str], jwt.encode)


def _httpx_request(api_base_url: str) -> GitHubRequest:
    async def request(method: str, path: str, **kwargs: object) -> GitHubResponse:
        try:
            import httpx
        except ImportError as error:
            raise GitHubApiError(
                "httpx is not installed. Install the backend github extra to enable GitHub."
            ) from error
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "CodePilot"}
        token = kwargs.get("token")
        if isinstance(token, str):
            headers["Authorization"] = f"Bearer {token}"
        accept = kwargs.get("accept")
        if isinstance(accept, str):
            headers["Accept"] = accept
        json_payload = kwargs.get("json_payload")
        async with httpx.AsyncClient(base_url=api_base_url, timeout=30) as client:
            response = await client.request(method, path, headers=headers, json=json_payload)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        return GitHubResponse(response.status_code, dict(response.headers), payload, response.text)

    return request
