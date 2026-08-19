"""Minimal rootless sidecar API for isolated Fix verification."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from codepilot.services.repair import validate_unified_patch

app = FastAPI(title="CodePilot Fix Sandbox")


class VerifyPayload(BaseModel):
    repository_url: str = Field(min_length=1, max_length=2_048)
    commit_sha: str = Field(min_length=40, max_length=64)
    patch: str = Field(min_length=1, max_length=512_000)


@app.post("/verify")
async def verify(payload: VerifyPayload) -> dict[str, object]:
    parsed = urlsplit(payload.repository_url)
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
        raise HTTPException(
            status_code=400, detail="Only public GitHub HTTPS repositories are supported."
        )
    try:
        validate_unified_patch(payload.patch)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Patch validation failed.") from error
    root = Path(tempfile.mkdtemp(prefix="codepilot-fix-"))
    try:
        await _run(
            (
                "git",
                "clone",
                "--no-checkout",
                "--filter=blob:none",
                payload.repository_url,
                str(root / "repo"),
            ),
            root,
        )
        checkout = root / "repo"
        await _run(("git", "checkout", "--detach", payload.commit_sha), checkout)
        patch_file = root / "change.patch"
        patch_file.write_text(payload.patch, encoding="utf-8")
        await _run(("git", "apply", "--check", str(patch_file)), checkout)
        await _run(("git", "apply", "--whitespace=nowarn", str(patch_file)), checkout)
        setup = _setup_command(checkout)
        if setup is not None:
            await _run(setup, checkout)
        command = _test_command(checkout)
        if command is None:
            raise HTTPException(status_code=422, detail="No supported test command was detected.")
        await _run(command, checkout)
        return {
            "commands": [" ".join(command)],
            "files": _changed_files(checkout, payload.commit_sha),
        }
    except HTTPException:
        raise
    except TimeoutError as error:
        raise HTTPException(status_code=504, detail="Sandbox test timeout.") from error
    except RuntimeError as error:
        raise HTTPException(status_code=422, detail="Sandbox verification failed.") from error
    finally:
        shutil.rmtree(root, ignore_errors=True)


async def _run(command: tuple[str, ...], cwd: Path) -> None:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise
    if process.returncode != 0:
        detail = (stderr or stdout).decode(errors="replace")[-500:]
        raise RuntimeError(detail)


def _test_command(root: Path) -> tuple[str, ...] | None:
    if (
        (root / "pyproject.toml").exists()
        or (root / "pytest.ini").exists()
        or (root / "tests").is_dir()
    ):
        return ("python", "-m", "pytest", "-q")
    if (root / "package.json").exists():
        return ("npm", "test", "--", "--run")
    if (root / "go.mod").exists():
        return ("go", "test", "./...")
    if list(root.glob("*.sln")) or list(root.glob("*.csproj")):
        return ("dotnet", "test", "--no-restore")
    return None


def _setup_command(root: Path) -> tuple[str, ...] | None:
    if (root / "package-lock.json").exists():
        return ("npm", "ci", "--ignore-scripts")
    return None


def _changed_files(root: Path, commit_sha: str) -> dict[str, str]:
    process = _run_sync(("git", "diff", "--name-only", commit_sha), root)
    files: dict[str, str] = {}
    for path in process.splitlines():
        candidate = root / path
        if candidate.is_file():
            files[path] = candidate.read_text(encoding="utf-8")
    return files


def _run_sync(command: tuple[str, ...], cwd: Path) -> str:
    result = subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, check=False, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError("Sandbox could not inspect changed files.")
    return result.stdout
