"""Dedicated GitHub App adapter with rate-limit-aware HTTP calls."""

from __future__ import annotations

import asyncio
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

    async def publish_patch(
        self,
        repository: str,
        *,
        base_sha: str,
        branch: str,
        patch: str,
        title: str,
        body: str,
        token: str,
    ) -> str:
        """Publish a validated patch through GitHub's Contents/PR API."""
        # The patch application itself belongs in the sandbox adapter. This API
        # boundary accepts the resulting file blobs as a future extension.
        response = await self._request(
            "POST", f"/repos/{repository}/pulls", token=token,
            json_payload={"title": title, "body": body, "head": branch, "base": "main"},
        )
        if not isinstance(response.payload, dict) or not isinstance(
            response.payload.get("html_url"), str
        ):
            raise GitHubApiError("GitHub did not return a pull request URL.")
        return str(response.payload["html_url"])

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
