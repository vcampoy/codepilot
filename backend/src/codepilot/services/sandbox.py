"""HTTP port for the isolated Fix verification sidecar."""

from __future__ import annotations

from dataclasses import dataclass

from codepilot.services.repair import (
    RepairExecutionError,
    SandboxVerifier,
    validate_unified_patch,
)


@dataclass(frozen=True, slots=True)
class HttpSandboxVerifier(SandboxVerifier):
    endpoint: str
    timeout_seconds: float = 300

    async def verify(self, repository_url: str, commit_sha: str, patch: str) -> tuple[str, ...]:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.endpoint.rstrip('/')}/verify",
                    json={
                        "repository_url": repository_url,
                        "commit_sha": commit_sha,
                        "patch": patch,
                    },
                )
        except Exception as error:
            raise RepairExecutionError("Repair sandbox is unavailable.") from error
        if response.status_code >= 400:
            raise RepairExecutionError("Repair verification failed in the sandbox.")
        try:
            payload = response.json()
            commands = payload.get("commands")
            files = payload.get("files")
        except (TypeError, ValueError) as error:
            raise RepairExecutionError("Repair sandbox returned an invalid response.") from error
        if not isinstance(commands, list) or not all(isinstance(item, str) for item in commands):
            raise RepairExecutionError("Repair sandbox returned no test commands.")
        if not isinstance(files, dict) or not all(
            isinstance(path, str) and (isinstance(content, str) or content is None)
            for path, content in files.items()
        ):
            raise RepairExecutionError("Repair sandbox returned no verified files.")
        try:
            expected_paths = set(validate_unified_patch(patch))
        except ValueError as error:
            raise RepairExecutionError("Repair patch validation failed.") from error
        if not expected_paths.issubset(files):
            raise RepairExecutionError("Repair sandbox did not verify every changed file.")
        return tuple(commands)
