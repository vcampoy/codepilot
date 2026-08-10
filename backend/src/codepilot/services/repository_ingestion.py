"""Secure ingestion and metadata inspection for public Git repositories."""

from __future__ import annotations

import asyncio
import fnmatch
import ipaddress
import os
import shutil
import signal
import socket
import stat
import subprocess  # nosec B404: required for the validated Git history boundary.
import tempfile
import time
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import SplitResult, urlsplit

from codepilot.core.settings import Settings


class RepositoryIngestionError(Exception):
    """Base class for expected repository ingestion failures."""

    code: str = "repository_ingestion_failed"
    default_message: str = "Repository ingestion failed."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.default_message)


class UnsupportedRepositoryUrlError(RepositoryIngestionError):
    """The submitted repository URL is not an allowed public HTTPS URL."""

    code = "unsupported_repository_url"
    default_message = "Only public Git HTTPS URLs are supported."


class PrivateRepositoryTargetError(RepositoryIngestionError):
    """The repository hostname resolves to a private or otherwise unsafe target."""

    code = "private_repository_target"
    default_message = "Repository target must resolve to a public address."


class RepositoryTargetResolutionError(RepositoryIngestionError):
    """The repository hostname could not be resolved safely."""

    code = "repository_target_resolution_failed"
    default_message = "Repository target could not be resolved safely."


class RepositoryCloneError(RepositoryIngestionError):
    """Git could not clone the repository."""

    code = "repository_clone_failed"
    default_message = "Repository could not be cloned."


class RepositoryTimeoutError(RepositoryIngestionError):
    """The clone or Git metadata operation exceeded its deadline."""

    code = "repository_ingestion_timeout"
    default_message = "Repository ingestion timed out."


class RepositoryCancelledError(RepositoryIngestionError):
    """Ingestion was cancelled before it completed."""

    code = "repository_ingestion_cancelled"
    default_message = "Repository ingestion was cancelled."


class RepositorySizeLimitError(RepositoryIngestionError):
    """The repository exceeded the configured byte limit."""

    code = "repository_size_limit_exceeded"
    default_message = "Repository exceeds the maximum allowed size."


class RepositoryFileCountLimitError(RepositoryIngestionError):
    """The repository exceeded the configured file-count limit."""

    code = "repository_file_count_limit_exceeded"
    default_message = "Repository contains too many files."


class RepositoryInspectionError(RepositoryIngestionError):
    """Repository metadata could not be inspected safely."""

    code = "repository_inspection_failed"
    default_message = "Repository could not be inspected."


class RepositoryMetadataError(RepositoryInspectionError):
    """A Git metadata command failed or returned invalid metadata."""

    code = "repository_metadata_failed"
    default_message = "Repository metadata could not be resolved."


class RepositoryOutputLimitError(RepositoryMetadataError):
    """A Git metadata command emitted more output than allowed."""

    code = "repository_output_limit_exceeded"
    default_message = "Repository metadata output exceeded the maximum allowed size."


class RepositoryWorkspaceError(RepositoryIngestionError):
    """An isolated temporary workspace could not be created."""

    code = "repository_workspace_failed"
    default_message = "Repository workspace could not be created."


class RepositoryCleanupError(RepositoryIngestionError):
    """An isolated temporary workspace could not be removed."""

    code = "repository_cleanup_failed"
    default_message = "Repository workspace could not be removed."


class RepositoryProcessTerminationError(RepositoryIngestionError):
    """A Git process tree could not be terminated safely."""

    code = "repository_process_termination_failed"
    default_message = "Repository process could not be terminated safely."


@dataclass(frozen=True, slots=True)
class IngestionLimits:
    """Resource limits applied to each isolated repository checkout."""

    timeout_seconds: float = 300.0
    max_repository_bytes: int = 100_000_000
    max_file_count: int = 50_000
    monitor_interval_seconds: float = 0.05

    @classmethod
    def from_settings(cls, settings: Settings) -> IngestionLimits:
        """Build ingestion limits from the shared application settings."""
        return cls(
            timeout_seconds=float(settings.analysis_timeout_seconds),
            max_repository_bytes=settings.repository_max_size_bytes,
            max_file_count=settings.repository_max_file_count,
        )

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_repository_bytes <= 0:
            raise ValueError("max_repository_bytes must be positive")
        if self.max_file_count <= 0:
            raise ValueError("max_file_count must be positive")
        if self.monitor_interval_seconds <= 0:
            raise ValueError("monitor_interval_seconds must be positive")


@dataclass(frozen=True, slots=True)
class ValidatedRepositoryTarget:
    """A URL whose public DNS addresses are pinned into the Git connection."""

    url: str
    hostname: str
    addresses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    """Trusted metadata about an untrusted repository checkout."""

    repository_path: Path
    commit_sha: str
    default_branch: str | None
    primary_languages: tuple[str, ...]
    file_count: int
    source_size_bytes: int


class GitClient(Protocol):
    """Git operations required by the ingestion service."""

    async def clone(
        self,
        target: ValidatedRepositoryTarget,
        destination: Path,
        timeout_seconds: float,
        max_repository_bytes: int,
        max_file_count: int,
        cancellation_event: asyncio.Event | None,
        monitor_interval_seconds: float = 0.05,
    ) -> None: ...

    async def resolve_commit_sha(
        self,
        repository_path: Path,
        cancellation_event: asyncio.Event | None = None,
    ) -> str: ...

    async def resolve_default_branch(
        self,
        repository_path: Path,
        cancellation_event: asyncio.Event | None = None,
    ) -> str | None: ...


_IGNORED_DIRECTORY_NAMES: Final = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "vendor",
        "vendors",
        "packages",
        "bin",
        "obj",
        "build",
        "dist",
        "out",
        "target",
        "coverage",
        ".next",
        ".nuxt",
        ".venv",
        "venv",
        "__pycache__",
    }
)
_GENERATED_FILE_PATTERNS: Final = (
    "*.generated.*",
    "*.g.*",
    "*.designer.*",
    "*.min.*",
    "*.map",
    "*_pb2.py",
    "*_pb2_grpc.py",
)
_LANGUAGE_BY_SUFFIX: Final = {
    ".py": "Python",
    ".pyi": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".go": "Go",
    ".rs": "Rust",
    ".cs": "C#",
    ".fs": "F#",
    ".cpp": "C++",
    ".cc": "C++",
    ".c": "C",
    ".h": "C/C++",
    ".hpp": "C++",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".sql": "SQL",
    ".sh": "Shell",
    ".ps1": "PowerShell",
}
_UNSAFE_HOSTNAME_SUFFIXES: Final = (".localhost", ".local", ".internal", ".lan")
_SHARED_ADDRESS_NETWORK: Final = ipaddress.ip_network("100.64.0.0/10")
_MAX_METADATA_OUTPUT_BYTES: Final = 4_096
_PROCESS_IO_CHUNK_BYTES: Final = 1_024
_PROXY_VARIABLES: Final = {
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "NO_PROXY",
    "no_proxy",
}


def _resolve_public_addresses(hostname: str) -> list[str]:
    """Resolve every address family so private IPv4/IPv6 targets are rejected."""
    try:
        records = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise RepositoryTargetResolutionError() from error
    addresses: list[str] = []
    for record in records:
        address = record[4][0]
        if isinstance(address, str):
            addresses.append(address)
    return list(dict.fromkeys(addresses))


def _is_unsafe_address(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return True
    return (
        not parsed.is_global
        or parsed in _SHARED_ADDRESS_NETWORK
        or parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_multicast
        or parsed.is_unspecified
        or parsed.is_reserved
    )


def _parse_public_repository_hostname(url: str) -> str:
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise UnsupportedRepositoryUrlError() from error
    if not _is_supported_repository_url(parsed, hostname, port):
        raise UnsupportedRepositoryUrlError()
    if hostname is None:
        raise UnsupportedRepositoryUrlError()
    return hostname.rstrip(".").casefold()


def _is_supported_repository_url(
    parsed: SplitResult, hostname: str | None, port: int | None
) -> bool:
    return (
        parsed.scheme.casefold() == "https"
        and hostname is not None
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and parsed.path not in {"", "/"}
        and port in {None, 443}
    )


def _validate_public_repository_hostname(hostname: str) -> None:
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if _is_unsafe_address(hostname):
            raise PrivateRepositoryTargetError()
    if hostname == "localhost" or hostname.endswith(_UNSAFE_HOSTNAME_SUFFIXES):
        raise PrivateRepositoryTargetError()


async def _resolve_public_repository_addresses(
    hostname: str, resolve_addresses: Callable[[str], Sequence[str]]
) -> tuple[str, ...]:
    try:
        addresses = tuple(await asyncio.to_thread(resolve_addresses, hostname))
    except RepositoryIngestionError:
        raise
    except OSError as error:
        raise RepositoryTargetResolutionError() from error
    if not addresses or any(_is_unsafe_address(address) for address in addresses):
        raise PrivateRepositoryTargetError()
    return addresses


class PublicHttpsRepositoryUrlValidator:
    """Validate URLs and pin their public DNS destinations for Git."""

    def __init__(self, resolve_addresses: Callable[[str], Sequence[str]] | None = None) -> None:
        self._resolve_addresses = resolve_addresses or _resolve_public_addresses

    async def validate(self, url: str) -> ValidatedRepositoryTarget:
        hostname = _parse_public_repository_hostname(url)
        _validate_public_repository_hostname(hostname)
        addresses = await _resolve_public_repository_addresses(hostname, self._resolve_addresses)
        return ValidatedRepositoryTarget(url, hostname, addresses)


def _is_generated_file(path: Path) -> bool:
    name = path.name.casefold()
    return "generated" in name or any(
        fnmatch.fnmatch(name, pattern) for pattern in _GENERATED_FILE_PATTERNS
    )


def _iter_files(root: Path, *, include_git: bool) -> Iterator[Path]:
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                path = Path(entry.path)
                if _skip_entry(entry):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if _skip_directory(entry.name, include_git):
                        continue
                    yield from _iter_files(path, include_git=include_git)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                if not include_git and _is_generated_file(path):
                    continue
                yield path
    except (OSError, RecursionError) as error:
        raise RepositoryInspectionError() from error


def _skip_entry(entry: os.DirEntry[str]) -> bool:
    return entry.is_symlink()


def _skip_directory(name: str, include_git: bool) -> bool:
    return not include_git and name in _IGNORED_DIRECTORY_NAMES


def _measure_storage(
    root: Path,
    *,
    max_repository_bytes: int | None = None,
    max_file_count: int | None = None,
) -> tuple[int, int]:
    total_bytes = 0
    file_count = 0
    try:
        for path in _iter_files(root, include_git=True):
            size = _file_size(path)
            total_bytes += size
            if _counts_storage_file(path, root):
                file_count += 1
            _enforce_storage_limits(total_bytes, file_count, max_repository_bytes, max_file_count)
    except (OSError, RecursionError) as error:
        raise RepositoryInspectionError() from error
    return total_bytes, file_count


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError as error:
        raise RepositoryInspectionError() from error


def _counts_storage_file(path: Path, root: Path) -> bool:
    relative_parts = path.relative_to(root).parts
    return bool(relative_parts) and relative_parts[0] != ".git"


def _enforce_storage_limits(
    total_bytes: int,
    file_count: int,
    max_repository_bytes: int | None,
    max_file_count: int | None,
) -> None:
    if max_repository_bytes is not None and total_bytes > max_repository_bytes:
        raise RepositorySizeLimitError()
    if max_file_count is not None and file_count > max_file_count:
        raise RepositoryFileCountLimitError()


def _inspect_worktree(root: Path) -> tuple[int, int, tuple[str, ...]]:
    file_count = 0
    source_size_bytes = 0
    language_counts: dict[str, int] = {}
    try:
        for path in _iter_files(root, include_git=False):
            file_count += 1
            language = _LANGUAGE_BY_SUFFIX.get(path.suffix.casefold())
            if language is None:
                continue
            try:
                source_size_bytes += path.stat().st_size
            except OSError as error:
                raise RepositoryInspectionError() from error
            language_counts[language] = language_counts.get(language, 0) + 1
    except (OSError, RecursionError) as error:
        raise RepositoryInspectionError() from error
    primary_languages = tuple(
        language
        for language, _count in sorted(
            language_counts.items(), key=lambda item: (-item[1], item[0])
        )
    )
    return file_count, source_size_bytes, primary_languages


def _validate_commit_sha(commit_sha: str) -> str:
    normalized = commit_sha.strip()
    if len(normalized) not in {40, 64} or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise RepositoryMetadataError()
    return normalized


def _safe_process_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for variable in list(environment):
        if variable.startswith("GIT_") or variable in _PROXY_VARIABLES:
            environment.pop(variable, None)
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
        }
    )
    return environment


class SubprocessGitClient:
    """Run Git without a shell and with repository-content execution disabled."""

    def __init__(
        self,
        executable: str = "git",
        command_prefix: Sequence[str] = (),
        metadata_timeout_seconds: float = 30.0,
    ) -> None:
        if metadata_timeout_seconds <= 0:
            raise ValueError("metadata_timeout_seconds must be positive")
        self._executable = executable
        self._command_prefix = tuple(command_prefix)
        self._metadata_timeout_seconds = metadata_timeout_seconds

    def _command(self, *arguments: str) -> list[str]:
        return [self._executable, *self._command_prefix, *arguments]

    async def clone(
        self,
        target: ValidatedRepositoryTarget,
        destination: Path,
        timeout_seconds: float,
        max_repository_bytes: int,
        max_file_count: int,
        cancellation_event: asyncio.Event | None,
        monitor_interval_seconds: float = 0.05,
    ) -> None:
        if monitor_interval_seconds <= 0:
            raise ValueError("monitor_interval_seconds must be positive")
        arguments = self._command(
            "-c",
            "protocol.file.allow=never",
            "-c",
            "http.followRedirects=false",
            "-c",
            "http.sslVerify=true",
        )
        for address in target.addresses:
            arguments.extend(["-c", f"http.curloptResolve={target.hostname}:443:{address}"])
        arguments.extend(
            [
                "clone",
                "--depth",
                "1",
                "--no-tags",
                "--single-branch",
                "--no-recurse-submodules",
                target.url,
                str(destination),
            ]
        )
        await self._run_clone_process(
            arguments,
            destination.parent,
            timeout_seconds,
            max_repository_bytes,
            max_file_count,
            cancellation_event,
            monitor_interval_seconds,
        )

    async def resolve_commit_sha(
        self,
        repository_path: Path,
        cancellation_event: asyncio.Event | None = None,
    ) -> str:
        stdout = await self._run_metadata_command(
            self._command("-C", str(repository_path), "rev-parse", "HEAD"),
            cancellation_event=cancellation_event,
        )
        return _validate_commit_sha(stdout)

    async def resolve_default_branch(
        self,
        repository_path: Path,
        cancellation_event: asyncio.Event | None = None,
    ) -> str | None:
        symbolic_ref = await self._run_metadata_command(
            self._command(
                "-C",
                str(repository_path),
                "symbolic-ref",
                "--quiet",
                "--short",
                "refs/remotes/origin/HEAD",
            ),
            allow_failure=True,
            cancellation_event=cancellation_event,
        )
        branch = symbolic_ref.strip().removeprefix("origin/")
        if branch:
            return branch
        current_branch = await self._run_metadata_command(
            self._command("-C", str(repository_path), "branch", "--show-current"),
            allow_failure=True,
            cancellation_event=cancellation_event,
        )
        return current_branch.strip() or None

    async def _wait_for_metadata_output(
        self,
        process: asyncio.subprocess.Process,
        communicate_task: asyncio.Task[bytes],
        cancellation_event: asyncio.Event | None,
    ) -> bytes:
        if cancellation_event is None:
            return await asyncio.wait_for(
                asyncio.shield(communicate_task), timeout=self._metadata_timeout_seconds
            )

        cancellation_task = asyncio.create_task(cancellation_event.wait())
        try:
            done, _pending = await asyncio.wait(
                (communicate_task, cancellation_task),
                timeout=self._metadata_timeout_seconds,
            )
            if cancellation_task in done and cancellation_event.is_set():
                raise RepositoryCancelledError()
            if communicate_task not in done:
                raise RepositoryTimeoutError()
            return communicate_task.result()
        finally:
            cancellation_task.cancel()
            await asyncio.gather(cancellation_task, return_exceptions=True)

    async def _collect_metadata_output(
        self,
        process: asyncio.subprocess.Process,
        communicate_task: asyncio.Task[bytes],
        cancellation_event: asyncio.Event | None,
    ) -> bytes:
        try:
            return await self._wait_for_metadata_output(
                process, communicate_task, cancellation_event
            )
        except TimeoutError as error:
            raise RepositoryTimeoutError() from error
        except RepositoryOutputLimitError:
            raise
        except asyncio.CancelledError:
            raise
        finally:
            if not communicate_task.done():
                await self._stop_process_tree(process, communicate_task)

    async def _ensure_metadata_process_exit(
        self,
        process: asyncio.subprocess.Process,
        communicate_task: asyncio.Task[bytes],
    ) -> None:
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), timeout=0.5)
            except TimeoutError as error:
                await self._stop_process_tree(process, communicate_task)
                raise RepositoryTimeoutError() from error
        _close_process_transport(process)

    async def _run_metadata_command(
        self,
        arguments: list[str],
        *,
        allow_failure: bool = False,
        cancellation_event: asyncio.Event | None = None,
    ) -> str:
        try:
            process = await _create_git_process(arguments, capture_stdout=True)
        except OSError as error:
            raise RepositoryMetadataError() from error
        communicate_task = asyncio.create_task(
            _read_bounded_stdout(process, _MAX_METADATA_OUTPUT_BYTES)
        )
        stdout = await self._collect_metadata_output(process, communicate_task, cancellation_event)
        await self._ensure_metadata_process_exit(process, communicate_task)
        if process.returncode != 0:
            if allow_failure:
                return ""
            raise RepositoryMetadataError()
        return stdout.decode("utf-8", errors="replace")

    async def _run_clone_process(
        self,
        arguments: list[str],
        working_directory: Path,
        timeout_seconds: float,
        max_repository_bytes: int,
        max_file_count: int,
        cancellation_event: asyncio.Event | None,
        monitor_interval_seconds: float,
    ) -> None:
        try:
            process = await _create_git_process(
                arguments, cwd=working_directory, capture_stdout=False
            )
        except OSError as error:
            raise RepositoryCloneError() from error

        communicate_task = asyncio.create_task(process.wait())
        try:
            await self._monitor_clone_process(
                process,
                communicate_task,
                working_directory,
                timeout_seconds,
                max_repository_bytes,
                max_file_count,
                cancellation_event,
                monitor_interval_seconds,
            )
            await communicate_task
        except asyncio.CancelledError:
            await self._stop_process_tree(process, communicate_task)
            raise
        finally:
            if not communicate_task.done():
                await self._stop_process_tree(process, communicate_task)
        _close_process_transport(process)
        if process.returncode != 0:
            raise RepositoryCloneError()

    async def _monitor_clone_process(
        self,
        process: asyncio.subprocess.Process,
        communicate_task: asyncio.Task[Any],
        working_directory: Path,
        timeout_seconds: float,
        max_repository_bytes: int,
        max_file_count: int,
        cancellation_event: asyncio.Event | None,
        monitor_interval_seconds: float,
    ) -> None:
        deadline = time.monotonic() + timeout_seconds
        while not communicate_task.done():
            if cancellation_event is not None and cancellation_event.is_set():
                await self._stop_process_tree(process, communicate_task)
                raise RepositoryCancelledError()
            if time.monotonic() >= deadline:
                await self._stop_process_tree(process, communicate_task)
                raise RepositoryTimeoutError()
            try:
                _measure_storage(
                    working_directory,
                    max_repository_bytes=max_repository_bytes,
                    max_file_count=max_file_count,
                )
            except (RepositorySizeLimitError, RepositoryFileCountLimitError):
                await self._stop_process_tree(process, communicate_task)
                raise
            await asyncio.sleep(monitor_interval_seconds)

    @staticmethod
    async def _stop_process_tree(
        process: asyncio.subprocess.Process, communicate_task: asyncio.Task[Any]
    ) -> None:
        termination_failed = await _terminate_process(process)
        termination_failed = (
            await _drain_process_task(process, communicate_task)
        ) or termination_failed
        _close_process_transport(process)
        if process.returncode is None or termination_failed:
            raise RepositoryProcessTerminationError()


async def _terminate_process(process: asyncio.subprocess.Process) -> bool:
    if process.returncode is not None:
        return False
    try:
        await _terminate_process_tree(process, force=False)
        await asyncio.wait_for(process.wait(), timeout=0.5)
        return False
    except (OSError, TimeoutError):
        return await _force_terminate_process(process)


async def _force_terminate_process(process: asyncio.subprocess.Process) -> bool:
    try:
        await _terminate_process_tree(process, force=True)
        await asyncio.wait_for(process.wait(), timeout=0.5)
        return False
    except (OSError, TimeoutError):
        try:
            process.kill()
            await asyncio.wait_for(process.wait(), timeout=0.5)
            return False
        except (OSError, TimeoutError):
            return True


async def _drain_process_task(
    process: asyncio.subprocess.Process, communicate_task: asyncio.Task[Any]
) -> bool:
    if communicate_task.done():
        return False
    _close_process_stdout(process)
    try:
        await asyncio.wait_for(asyncio.shield(communicate_task), timeout=0.5)
        return False
    except TimeoutError:
        communicate_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(communicate_task), timeout=0.5)
            return False
        except (TimeoutError, asyncio.CancelledError):
            return True


async def _terminate_process_tree(process: asyncio.subprocess.Process, *, force: bool) -> None:
    if process.returncode is not None:
        return
    if os.name == "nt":
        await _terminate_windows_process(process, force)
    else:
        _terminate_posix_process(process, force)


async def _terminate_windows_process(process: asyncio.subprocess.Process, force: bool) -> None:
    arguments = ["taskkill", "/PID", str(process.pid), "/T"]
    if force:
        arguments.append("/F")
    try:
        killer = await asyncio.create_subprocess_exec(
            *arguments,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        await asyncio.wait_for(killer.wait(), timeout=0.5)
    except (OSError, TimeoutError):
        if force:
            process.kill()


def _terminate_posix_process(process: asyncio.subprocess.Process, force: bool) -> None:
    killpg = getattr(os, "killpg", None)
    if not callable(killpg):
        process.kill() if force else process.terminate()
        return
    signal_to_send = getattr(signal, "SIGKILL", signal.SIGTERM) if force else signal.SIGTERM
    try:
        killpg(process.pid, signal_to_send)
    except ProcessLookupError:
        return


def _close_process_stdout(process: asyncio.subprocess.Process) -> None:
    stream = process.stdout
    if stream is None:
        return
    transport = getattr(stream, "_transport", None)
    if transport is not None:
        transport.close()


def _close_process_transport(process: asyncio.subprocess.Process) -> None:
    transport = getattr(process, "_transport", None)
    if transport is not None:
        transport.close()


async def _create_git_process(
    arguments: list[str], *, cwd: Path | None = None, capture_stdout: bool
) -> asyncio.subprocess.Process:
    environment = _safe_process_environment()
    stdout = asyncio.subprocess.PIPE if capture_stdout else asyncio.subprocess.DEVNULL
    if os.name == "nt":
        return await asyncio.create_subprocess_exec(
            *arguments,
            cwd=cwd,
            stdout=stdout,
            stderr=asyncio.subprocess.DEVNULL,
            env=environment,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
        )
    return await asyncio.create_subprocess_exec(
        *arguments,
        cwd=cwd,
        stdout=stdout,
        stderr=asyncio.subprocess.DEVNULL,
        env=environment,
        start_new_session=True,
    )


async def _read_bounded_stdout(process: asyncio.subprocess.Process, maximum_bytes: int) -> bytes:
    if process.stdout is None:
        return b""
    chunks: list[bytes] = []
    total_bytes = 0
    while True:
        chunk = await process.stdout.read(_PROCESS_IO_CHUNK_BYTES)
        if not chunk:
            return b"".join(chunks)
        total_bytes += len(chunk)
        if total_bytes > maximum_bytes:
            raise RepositoryOutputLimitError()
        chunks.append(chunk)


class RepositoryIngestionService:
    """Validate, clone, inspect, and clean up one untrusted repository checkout."""

    def __init__(
        self,
        git_client: GitClient | None = None,
        resolve_addresses: Callable[[str], Sequence[str]] | None = None,
        limits: IngestionLimits | None = None,
        temporary_directory_factory: Callable[[str], str] | None = None,
    ) -> None:
        self._git_client = git_client or SubprocessGitClient()
        self._url_validator = PublicHttpsRepositoryUrlValidator(resolve_addresses)
        self._limits = limits or IngestionLimits()
        self._temporary_directory_factory = temporary_directory_factory or tempfile.mkdtemp

    @asynccontextmanager
    async def ingest(
        self,
        url: str,
        *,
        cancellation_event: asyncio.Event | None = None,
    ) -> AsyncIterator[RepositorySnapshot]:
        """Yield an inspected checkout and remove it when the context exits."""
        target = await self._url_validator.validate(url)
        if cancellation_event is not None and cancellation_event.is_set():
            raise RepositoryCancelledError()
        try:
            workspace = Path(self._temporary_directory_factory("codepilot-ingestion-"))
        except (OSError, TypeError, ValueError) as error:
            raise RepositoryWorkspaceError() from error
        repository_path = workspace / "repository"
        try:
            try:
                async with asyncio.timeout(self._limits.timeout_seconds):
                    await self._git_client.clone(
                        target,
                        repository_path,
                        self._limits.timeout_seconds,
                        self._limits.max_repository_bytes,
                        self._limits.max_file_count,
                        cancellation_event,
                        self._limits.monitor_interval_seconds,
                    )
                    if cancellation_event is not None and cancellation_event.is_set():
                        raise RepositoryCancelledError()
                    _measure_storage(
                        repository_path,
                        max_repository_bytes=self._limits.max_repository_bytes,
                        max_file_count=self._limits.max_file_count,
                    )
                    file_count, source_size_bytes, primary_languages = _inspect_worktree(
                        repository_path
                    )
                    commit_sha = _validate_commit_sha(
                        await self._git_client.resolve_commit_sha(
                            repository_path, cancellation_event
                        )
                    )
                    default_branch = await self._git_client.resolve_default_branch(
                        repository_path, cancellation_event
                    )
                    snapshot = RepositorySnapshot(
                        repository_path=repository_path,
                        commit_sha=commit_sha,
                        default_branch=default_branch,
                        primary_languages=primary_languages,
                        file_count=file_count,
                        source_size_bytes=source_size_bytes,
                    )
            except TimeoutError as error:
                raise RepositoryTimeoutError() from error
            except asyncio.CancelledError as error:
                raise RepositoryCancelledError() from error
            yield snapshot
        finally:
            try:
                await asyncio.to_thread(_remove_workspace, workspace)
            except OSError as error:
                raise RepositoryCleanupError() from error


def _remove_readonly(function: Callable[..., object], path: str, _error: object) -> None:
    os.chmod(path, stat.S_IWRITE)
    function(path)


def _remove_workspace(workspace: Path) -> None:
    if workspace.exists():
        shutil.rmtree(workspace, onerror=_remove_readonly)
