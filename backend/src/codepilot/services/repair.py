"""Ports and safety primitives for executing repair jobs.

The worker depends on these narrow interfaces so LLM, OCI verification and
GitHub publishing remain independently replaceable adapters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol

from codepilot.domain.fixes import FixTargetType


@dataclass(frozen=True, slots=True)
class RepairRequest:
    target_type: FixTargetType
    target_ids: tuple[str, ...]
    evidence: tuple[dict[str, object], ...]
    rules: str
    workspace_id: str = "default"


@dataclass(frozen=True, slots=True)
class RepairResponse:
    patch: str
    title: str
    description: str


class RepairGateway(Protocol):
    async def generate_repair(self, request: RepairRequest) -> RepairResponse: ...


class SandboxVerifier(Protocol):
    async def verify(self, repository_url: str, commit_sha: str, patch: str) -> tuple[str, ...]: ...


class PullRequestPublisher(Protocol):
    async def publish(
        self,
        repository_url: str,
        commit_sha: str,
        branch_name: str,
        patch: str,
        title: str,
        description: str,
        base_branch: str | None = None,
    ) -> str: ...


class RepairExecutionError(RuntimeError):
    """A repair could not be safely verified or published."""


class RepairExecutor:
    """Coordinate repair generation, sandbox verification and PR publication."""

    def __init__(
        self,
        gateway: RepairGateway,
        sandbox: SandboxVerifier,
        publisher: PullRequestPublisher,
    ) -> None:
        self._gateway = gateway
        self._sandbox = sandbox
        self._publisher = publisher

    async def execute(
        self,
        request: RepairRequest,
        *,
        repository_url: str,
        commit_sha: str,
        branch_name: str,
        base_branch: str | None = None,
    ) -> str:
        response = await self._gateway.generate_repair(request)
        paths = validate_unified_patch(response.patch)
        _validate_patch_scope(paths, request)
        try:
            commands = await self._sandbox.verify(repository_url, commit_sha, response.patch)
        except Exception as error:
            raise RepairExecutionError("Repair verification failed.") from error
        if not commands:
            raise RepairExecutionError("Repair verification did not run any tests.")
        try:
            return await self._publisher.publish(
                repository_url,
                commit_sha,
                branch_name,
                response.patch,
                response.title,
                response.description,
                base_branch,
            )
        except Exception as error:
            raise RepairExecutionError("Repair pull request could not be published.") from error


_PATCH_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$", re.MULTILINE)
_SECRET = re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]")
_GENERATED = re.compile(r"(?i)(^|/)(dist|build|node_modules|__pycache__)(/|$)|\.lock$")


def validate_unified_patch(patch: str, *, max_bytes: int = 512_000) -> tuple[str, ...]:
    """Validate patch paths and reject dangerous or non-source changes."""
    if not patch or len(patch.encode()) > max_bytes:
        raise ValueError("Repair patch is empty or exceeds the size limit.")
    paths: list[str] = []
    for left, right in _PATCH_HEADER.findall(patch):
        if left != right:
            raise ValueError("Rename patches are not supported.")
        path = right
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts or "\\" in path:
            raise ValueError("Patch contains an unsafe path.")
        if _GENERATED.search(path):
            raise ValueError("Generated files cannot be modified.")
        paths.append(path)
    if not paths:
        raise ValueError("Patch must contain unified diff headers.")
    if _SECRET.search(patch):
        raise ValueError("Patch appears to contain a secret assignment.")
    return tuple(dict.fromkeys(paths))


def _validate_patch_scope(paths: tuple[str, ...], request: RepairRequest) -> None:
    allowed = {
        str(item.get("path")) for item in request.evidence if isinstance(item.get("path"), str)
    }
    if allowed and any(path not in allowed for path in paths):
        raise RepairExecutionError("Repair patch modifies a path outside selected targets.")


@dataclass(frozen=True, slots=True)
class NoopSandboxVerifier:
    """Explicit development adapter; production must provide an OCI verifier."""

    async def verify(self, repository_url: str, commit_sha: str, patch: str) -> tuple[str, ...]:
        validate_unified_patch(patch)
        return ()
