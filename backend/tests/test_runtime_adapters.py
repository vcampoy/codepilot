import asyncio
import subprocess
from pathlib import Path

import httpx
import pytest

from codepilot.github.client import GitHubApiError, GitHubClient
from codepilot.github.contracts import GitHubResponse
from codepilot.github.publisher import GitHubAppPullRequestPublisher, _materialize_patch
from codepilot.sandbox_api import VerifyPayload, _test_command, verify
from codepilot.services.repair import RepairExecutionError
from codepilot.services.sandbox import HttpSandboxVerifier

_PATCH = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-a
+b
"""
_TEST_ROOTS = ("pyproject.toml", "package.json", "go.mod", "demo.csproj")


class _Response:
    status_code = 200

    def json(self) -> dict[str, object]:
        return {"commands": ["pytest -q"], "files": {"src/app.py": "b"}}


class _Client:
    async def __aenter__(self) -> "_Client":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def post(self, *_args: object, **_kwargs: object) -> _Response:
        return _Response()


def test_http_sandbox_accepts_commands_and_verified_files(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: _Client())
    result = asyncio.run(
        HttpSandboxVerifier("http://sandbox").verify(
            "https://github.com/acme/repo", "a" * 40, _PATCH
        )
    )
    assert result == ("pytest -q",)


def test_http_sandbox_rejects_missing_verified_files(monkeypatch: pytest.MonkeyPatch) -> None:
    class InvalidResponse(_Response):
        def json(self) -> dict[str, object]:
            return {"commands": ["pytest -q"]}

    class InvalidClient(_Client):
        async def post(self, *_args: object, **_kwargs: object) -> InvalidResponse:
            return InvalidResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: InvalidClient())
    with pytest.raises(RepairExecutionError, match="verified files"):
        asyncio.run(
            HttpSandboxVerifier("http://sandbox").verify(
                "https://github.com/acme/repo", "a" * 40, _PATCH
            )
        )


def test_http_sandbox_rejects_unverified_changed_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InvalidResponse(_Response):
        def json(self) -> dict[str, object]:
            return {"commands": ["pytest -q"], "files": {"other.py": "b"}}

    class InvalidClient(_Client):
        async def post(self, *_args: object, **_kwargs: object) -> InvalidResponse:
            return InvalidResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: InvalidClient())
    with pytest.raises(RepairExecutionError, match="every changed file"):
        asyncio.run(
            HttpSandboxVerifier("http://sandbox").verify(
                "https://github.com/acme/repo", "a" * 40, _PATCH
            )
        )


def test_sandbox_detects_supported_test_manifests(tmp_path: Path) -> None:
    expected = (
        ("python", "-m", "pytest", "-q"),
        ("npm", "test", "--", "--run"),
        ("go", "test", "./..."),
        ("dotnet", "test", "--no-restore"),
    )
    for filename, command in zip(_TEST_ROOTS, expected, strict=True):
        root = tmp_path / filename.replace(".", "-")
        root.mkdir()
        (root / filename).write_text("", encoding="utf-8")
        assert _test_command(root) == command


def test_sandbox_verify_uses_checkout_and_returns_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job = tmp_path / "job"
    job.mkdir()

    async def run(_command: tuple[str, ...], cwd: Path) -> None:
        (cwd / "repo").mkdir(exist_ok=True)

    monkeypatch.setattr("codepilot.sandbox_api.tempfile.mkdtemp", lambda **_kwargs: str(job))
    monkeypatch.setattr("codepilot.sandbox_api._run", run)
    monkeypatch.setattr("codepilot.sandbox_api._test_command", lambda _root: ("pytest",))
    monkeypatch.setattr(
        "codepilot.sandbox_api._changed_files", lambda _root, _sha: {"src/app.py": "b"}
    )
    result = asyncio.run(
        verify(
            VerifyPayload(
                repository_url="https://github.com/acme/repo", commit_sha="a" * 40, patch=_PATCH
            )
        )
    )
    assert result["files"] == {"src/app.py": "b"}


def test_github_client_publishes_blob_tree_commit_ref_and_pr() -> None:
    responses = [
        GitHubResponse(200, {}, {"tree": {"sha": "base-tree"}}),
        GitHubResponse(201, {}, {"sha": "blob-sha"}),
        GitHubResponse(201, {}, {"sha": "tree-sha"}),
        GitHubResponse(201, {}, {"sha": "commit-sha"}),
        GitHubResponse(201, {}, {}),
        GitHubResponse(201, {}, {"html_url": "https://github.com/acme/repo/pull/1"}),
    ]

    async def request(_method: str, _path: str, **_kwargs: object) -> GitHubResponse:
        return responses.pop(0)

    result = asyncio.run(
        GitHubClient(request=request).publish_files(  # type: ignore[arg-type]
            "acme/repo",
            base_sha="a" * 40,
            branch="fix-1",
            files={"src/app.py": "b"},
            title="Fix",
            body="Reason",
            base_branch="develop",
            token="token",
        )
    )
    assert result.endswith("/pull/1")
    assert not responses


def test_github_client_removes_branch_when_pull_request_creation_fails() -> None:
    responses = [
        GitHubResponse(200, {}, {"tree": {"sha": "base-tree"}}),
        GitHubResponse(201, {}, {"sha": "blob-sha"}),
        GitHubResponse(201, {}, {"sha": "tree-sha"}),
        GitHubResponse(201, {}, {"sha": "commit-sha"}),
        GitHubResponse(201, {}, {}),
        GitHubResponse(422, {}, {}),
        GitHubResponse(204, {}, {}),
    ]
    calls: list[tuple[str, str]] = []

    async def request(method: str, path: str, **_kwargs: object) -> GitHubResponse:
        calls.append((method, path))
        return responses.pop(0)

    with pytest.raises(GitHubApiError):
        asyncio.run(
            GitHubClient(request=request).publish_files(
                "acme/repo",
                base_sha="a" * 40,
                branch="fix-1",
                files={"src/app.py": "b"},
                title="Fix",
                body="Reason",
                base_branch="develop",
                token="token",
            )
        )
    assert calls[-1] == ("DELETE", "/repos/acme/repo/git/refs/heads/fix-1")


def test_publisher_delegates_materialized_files(monkeypatch: pytest.MonkeyPatch) -> None:
    class Authenticator:
        def create_app_token(self) -> str:
            return "app-token"

    class Client:
        async def publish_files(self, *_args: object, **kwargs: object) -> str:
            assert kwargs["base_branch"] == "develop"
            return "https://github.com/acme/repo/pull/1"

    monkeypatch.setattr(
        "codepilot.github.publisher._materialize_patch", lambda *_args: {"src/app.py": "b"}
    )
    publisher = GitHubAppPullRequestPublisher(
        Client(),  # type: ignore[arg-type]
        Authenticator(),  # type: ignore[arg-type]
        "installation-token",
    )
    result = asyncio.run(
        publisher.publish(
            "https://github.com/acme/repo",
            "a" * 40,
            "fix-1",
            _PATCH,
            "Fix",
            "Reason",
            "develop",
        )
    )
    assert result.endswith("/pull/1")


def test_materialize_patch_reads_changed_file(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(("git", "init", str(source)), check=True, capture_output=True)
    subprocess.run(
        ("git", "-C", str(source), "config", "user.email", "test@example.com"), check=True
    )
    subprocess.run(("git", "-C", str(source), "config", "user.name", "Test"), check=True)
    (source / "app.py").write_text("a\n", encoding="utf-8")
    subprocess.run(("git", "-C", str(source), "add", "."), check=True)
    subprocess.run(
        ("git", "-C", str(source), "commit", "-m", "base"), check=True, capture_output=True
    )
    sha = subprocess.run(
        ("git", "-C", str(source), "rev-parse", "HEAD"), check=True, capture_output=True, text=True
    ).stdout.strip()
    patch = _PATCH.replace("src/app.py", "app.py")
    assert _materialize_patch(str(source), sha, patch) == {"app.py": "b\n"}
