import asyncio
import json
import os
import subprocess  # nosec B404: test-owned executable and arguments are fixed constants.
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

import codepilot.services.repository_ingestion as ingestion
from codepilot.services.repository_ingestion import (
    IngestionLimits,
    PrivateRepositoryTargetError,
    RepositoryCancelledError,
    RepositoryFileCountLimitError,
    RepositoryIngestionError,
    RepositoryIngestionService,
    RepositoryInspectionError,
    RepositoryMetadataError,
    RepositoryOutputLimitError,
    RepositoryProcessTerminationError,
    RepositorySizeLimitError,
    RepositoryTimeoutError,
    SubprocessGitClient,
    UnsupportedRepositoryUrlError,
    ValidatedRepositoryTarget,
)

_PUBLIC_TEST_URL: Final = "https://example.com/acme/repository.git"


def _create_local_git_repository(path: Path) -> None:
    # The executable and arguments are test-owned constants for this local fixture.
    subprocess.run(  # nosec B603, B607
        ["git", "init", "--initial-branch", "main", str(path)], check=True
    )
    # The executable and arguments are test-owned constants for this local fixture.
    subprocess.run(  # nosec B603, B607
        ["git", "-C", str(path), "config", "user.email", "tests@example.com"],
        check=True,
    )
    # The executable and arguments are test-owned constants for this local fixture.
    subprocess.run(  # nosec B603, B607
        ["git", "-C", str(path), "config", "user.name", "CodePilot Tests"], check=True
    )
    (path / "src").mkdir()
    (path / "src" / "main.py").write_text("print('untrusted content')\n", encoding="utf-8")
    (path / "src" / "app.ts").write_text("export const app = true;\n", encoding="utf-8")
    (path / "README.md").write_text("Repository fixture\n", encoding="utf-8")
    (path / "node_modules").mkdir()
    (path / "node_modules" / "ignored.js").write_text("ignored\n", encoding="utf-8")
    (path / "vendor").mkdir()
    (path / "vendor" / "ignored.go").write_text("ignored\n", encoding="utf-8")
    (path / "dist").mkdir()
    (path / "dist" / "bundle.js").write_text("ignored\n", encoding="utf-8")
    (path / "generated.g.cs").write_text("ignored\n", encoding="utf-8")
    # The executable and arguments are test-owned constants for this local fixture.
    subprocess.run(  # nosec B603, B607
        ["git", "-C", str(path), "add", "."], check=True
    )
    # The executable and arguments are test-owned constants for this local fixture.
    subprocess.run(  # nosec B603, B607
        ["git", "-C", str(path), "commit", "-m", "fixture"], check=True
    )


class _LocalGitClient:
    def __init__(self, source_path: Path, *, failure: Exception | None = None) -> None:
        self._source_path = source_path
        self._failure = failure
        self.last_target: ValidatedRepositoryTarget | None = None

    async def clone(
        self,
        target: ValidatedRepositoryTarget,
        destination: Path,
        _timeout_seconds: float,
        _max_repository_bytes: int,
        _max_file_count: int,
        cancellation_event: asyncio.Event | None,
        _monitor_interval_seconds: float = 0.05,
    ) -> None:
        self.last_target = target
        if cancellation_event is not None and cancellation_event.is_set():
            raise RepositoryCancelledError()
        if self._failure is not None:
            raise self._failure
        await asyncio.to_thread(
            subprocess.run,
            ["git", "clone", "--depth", "1", "--no-tags", str(self._source_path), str(destination)],
            check=True,
            capture_output=True,
            text=True,
        )

    async def resolve_commit_sha(
        self, repository_path: Path, _cancellation_event: asyncio.Event | None = None
    ) -> str:
        # The executable and arguments are test-owned constants for this local fixture.
        completed = await asyncio.to_thread(
            subprocess.run,  # nosec B607
            ["git", "-C", str(repository_path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    async def resolve_default_branch(
        self, repository_path: Path, _cancellation_event: asyncio.Event | None = None
    ) -> str | None:
        # The executable and arguments are test-owned constants for this local fixture.
        completed = await asyncio.to_thread(
            subprocess.run,  # nosec B607, B603
            [
                "git",
                "-C",
                str(repository_path),
                "symbolic-ref",
                "--quiet",
                "--short",
                "refs/remotes/origin/HEAD",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            return None
        return completed.stdout.strip().removeprefix("origin/") or None


def _service(
    source_path: Path,
    *,
    limits: IngestionLimits | None = None,
    failure: Exception | None = None,
) -> tuple[RepositoryIngestionService, list[Path]]:
    created_directories: list[Path] = []

    def create_temporary_directory(prefix: str) -> str:
        directory = tempfile.mkdtemp(prefix=prefix)
        created_directories.append(Path(directory))
        return directory

    service = RepositoryIngestionService(
        git_client=_LocalGitClient(source_path, failure=failure),
        resolve_addresses=lambda _hostname: ["93.184.216.34"],
        limits=limits,
        temporary_directory_factory=create_temporary_directory,
    )
    return service, created_directories


def test_ingests_local_fixture_through_validated_public_url_and_cleans_up(tmp_path: Path) -> None:
    source_path = tmp_path / "source"
    source_path.mkdir()
    _create_local_git_repository(source_path)
    service, created_directories = _service(source_path)

    async def scenario() -> None:
        async with service.ingest(_PUBLIC_TEST_URL) as result:
            assert result.commit_sha
            assert len(result.commit_sha) == 40
            assert result.default_branch == "main"
            assert result.file_count == 3
            assert result.source_size_bytes == len(
                (result.repository_path / "src" / "main.py").read_bytes()
            ) + len((result.repository_path / "src" / "app.ts").read_bytes())
            assert result.primary_languages == ("Python", "TypeScript")
            checkout_path = result.repository_path
            assert checkout_path.is_dir()

        assert created_directories
        assert all(not directory.exists() for directory in created_directories)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/acme/repository.git",
        "ssh://git@example.com/acme/repository.git",
        "file:///tmp/repository",
        "C:\\repositories\\repository",
        "https://localhost/acme/repository.git",
        "https://127.0.0.1/acme/repository.git",
        "https://user@example.com/acme/repository.git",
        "https://example.com/acme/repository.git?ref=main",
        "https://example.com/acme/repository.git#fragment",
        "https://example.com:8443/acme/repository.git",
        "https://example.com/",
    ],
)
def test_rejects_unsupported_or_internal_repository_targets(tmp_path: Path, url: str) -> None:
    source_path = tmp_path / "source"
    source_path.mkdir()
    service, _created_directories = _service(source_path)

    async def scenario() -> None:
        with pytest.raises((UnsupportedRepositoryUrlError, PrivateRepositoryTargetError)):
            async with service.ingest(url):
                pass

    asyncio.run(scenario())


def test_enforces_file_count_limit_and_cleans_up(tmp_path: Path) -> None:
    source_path = tmp_path / "source"
    source_path.mkdir()
    _create_local_git_repository(source_path)
    service, created_directories = _service(source_path, limits=IngestionLimits(max_file_count=1))

    async def scenario() -> None:
        with pytest.raises(RepositoryFileCountLimitError):
            async with service.ingest(_PUBLIC_TEST_URL):
                pass
        assert created_directories
        assert all(not directory.exists() for directory in created_directories)

    asyncio.run(scenario())


def test_enforces_repository_size_limit_and_cleans_up(tmp_path: Path) -> None:
    source_path = tmp_path / "source"
    source_path.mkdir()
    _create_local_git_repository(source_path)
    service, created_directories = _service(
        source_path, limits=IngestionLimits(max_repository_bytes=1)
    )

    async def scenario() -> None:
        with pytest.raises(RepositorySizeLimitError):
            async with service.ingest(_PUBLIC_TEST_URL):
                pass
        assert created_directories
        assert all(not directory.exists() for directory in created_directories)

    asyncio.run(scenario())


def test_rejects_private_dns_resolution(tmp_path: Path) -> None:
    source_path = tmp_path / "source"
    source_path.mkdir()
    service = RepositoryIngestionService(
        git_client=_LocalGitClient(source_path),
        resolve_addresses=lambda _hostname: ["10.0.0.5"],
    )

    async def scenario() -> None:
        with pytest.raises(PrivateRepositoryTargetError):
            async with service.ingest(_PUBLIC_TEST_URL):
                pass

    asyncio.run(scenario())


@pytest.mark.parametrize("address", ["100.64.0.1", "198.18.0.1", "192.0.2.1"])
def test_rejects_shared_and_non_public_dns_resolution(tmp_path: Path, address: str) -> None:
    source_path = tmp_path / "source"
    source_path.mkdir()
    service = RepositoryIngestionService(
        git_client=_LocalGitClient(source_path),
        resolve_addresses=lambda _hostname: [address],
    )

    async def scenario() -> None:
        with pytest.raises(PrivateRepositoryTargetError):
            async with service.ingest(_PUBLIC_TEST_URL):
                pass

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", [RepositoryTimeoutError(), RepositoryCancelledError()])
def test_clone_failure_cleans_up_isolated_directory(tmp_path: Path, failure: Exception) -> None:
    source_path = tmp_path / "source"
    source_path.mkdir()
    service, created_directories = _service(source_path, failure=failure)

    async def scenario() -> None:
        with pytest.raises(type(failure)):
            async with service.ingest(_PUBLIC_TEST_URL):
                pass
        assert created_directories
        assert all(not directory.exists() for directory in created_directories)

    asyncio.run(scenario())


def test_cancellation_is_rejected_before_clone(tmp_path: Path) -> None:
    source_path = tmp_path / "source"
    source_path.mkdir()
    service, created_directories = _service(source_path)
    cancellation_event = asyncio.Event()
    cancellation_event.set()

    async def scenario() -> None:
        with pytest.raises(RepositoryCancelledError):
            async with service.ingest(_PUBLIC_TEST_URL, cancellation_event=cancellation_event):
                pass
        assert not created_directories

    asyncio.run(scenario())


def _write_git_stub(path: Path, record_path: Path, mode: str) -> None:
    path.write_text(
        """
import json
import os
import pathlib
import subprocess
import sys
import time

args = sys.argv[1:]
record_path = pathlib.Path(os.environ["STUB_RECORD"])
record_path.write_text(json.dumps({"args": args, "env": dict(os.environ)}), encoding="utf-8")
mode = os.environ.get("STUB_MODE", "success")
if "clone" in args:
    pathlib.Path(args[-1]).mkdir(parents=True, exist_ok=True)
is_metadata = any(command in args for command in {"rev-parse", "symbolic-ref", "branch"})
should_block = (
    mode in {"timeout", "cancel"} and "clone" in args
) or (
    mode in {"metadata-timeout", "metadata-cancel"} and is_metadata
)
if should_block:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    record_path.with_suffix(".child").write_text(str(child.pid), encoding="ascii")
    while True:
        time.sleep(0.05)
if mode in {"output", "metadata-output"} and (
    (mode == "output" and "clone" in args) or (mode == "metadata-output" and is_metadata)
):
    output_bytes = int(os.environ.get("STUB_OUTPUT_BYTES", "8000000"))
    print("x" * output_bytes)
    print("e" * output_bytes, file=sys.stderr)
elif "rev-parse" in args:
    if mode == "failure":
        raise SystemExit(2)
    print(os.environ.get("STUB_SHA", "a" * 40))
elif "symbolic-ref" in args:
    print("origin/main")
""".strip(),
        encoding="utf-8",
    )


def _stub_client(tmp_path: Path, *, mode: str = "success") -> tuple[SubprocessGitClient, Path]:
    record_path = tmp_path / "stub-record.json"
    script_path = tmp_path / "git_stub.py"
    _write_git_stub(script_path, record_path, mode)
    os.environ["STUB_RECORD"] = str(record_path)
    os.environ["STUB_MODE"] = mode
    return (
        SubprocessGitClient(
            executable=sys.executable,
            command_prefix=(str(script_path),),
            metadata_timeout_seconds=0.2,
        ),
        record_path,
    )


def _public_target() -> ValidatedRepositoryTarget:
    return ValidatedRepositoryTarget(
        url=_PUBLIC_TEST_URL,
        hostname="example.com",
        addresses=("93.184.216.34", "93.184.216.35"),
    )


def _wait_for_file(path: Path) -> None:
    deadline = time.monotonic() + 3
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert path.exists()


def _wait_for_process_exit(pid: int) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.02)
    pytest.fail(f"process {pid} still running")


def test_dns_resolution_is_pinned_into_real_clone_arguments(tmp_path: Path) -> None:
    client, record_path = _stub_client(tmp_path)

    async def scenario() -> None:
        await client.clone(_public_target(), tmp_path / "checkout", 1, 1_000_000, 100, None)

    asyncio.run(scenario())
    record = json.loads(record_path.read_text(encoding="utf-8"))
    args = record["args"]
    assert "http.followRedirects=false" in args
    assert "http.curloptResolve=example.com:443:93.184.216.34" in args
    assert "http.curloptResolve=example.com:443:93.184.216.35" in args


def test_real_clone_subprocess_hardens_inherited_git_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, record_path = _stub_client(tmp_path)
    for name, value in {
        "GIT_SSL_NO_VERIFY": "1",
        "GIT_ASKPASS": "evil-helper",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.sslVerify",
        "GIT_CONFIG_VALUE_0": "false",
        "HTTPS_PROXY": "http://attacker.invalid:8080",
    }.items():
        monkeypatch.setenv(name, value)

    async def scenario() -> None:
        await client.clone(_public_target(), tmp_path / "checkout", 1, 1_000_000, 100, None)

    asyncio.run(scenario())
    environment = json.loads(record_path.read_text(encoding="utf-8"))["env"]
    assert "GIT_SSL_NO_VERIFY" not in environment
    assert "GIT_ASKPASS" not in environment
    assert "GIT_CONFIG_COUNT" not in environment
    assert "HTTPS_PROXY" not in environment
    assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
    assert environment["GIT_CONFIG_GLOBAL"] == os.devnull
    assert environment["GIT_TERMINAL_PROMPT"] == "0"


@pytest.mark.parametrize("mode", ["timeout", "cancel"])
def test_real_clone_termination_cleans_process_tree(tmp_path: Path, mode: str) -> None:
    client, record_path = _stub_client(tmp_path, mode=mode)
    cancellation_event = asyncio.Event()

    async def scenario() -> None:
        task = asyncio.create_task(
            client.clone(
                _public_target(), tmp_path / "checkout", 0.2, 1_000_000, 100, cancellation_event
            )
        )
        child_path = record_path.with_suffix(".child")
        await asyncio.to_thread(_wait_for_file, child_path)
        expected_error: type[RepositoryIngestionError]
        if mode == "cancel":
            cancellation_event.set()
            expected_error = RepositoryCancelledError
        else:
            expected_error = RepositoryTimeoutError
        with pytest.raises(expected_error):
            await task
        _wait_for_process_exit(int(child_path.read_text(encoding="ascii")))

    asyncio.run(scenario())


def test_real_metadata_timeout_terminates_process_tree(tmp_path: Path) -> None:
    client, record_path = _stub_client(tmp_path, mode="metadata-timeout")

    async def scenario() -> None:
        with pytest.raises(RepositoryTimeoutError):
            await client.resolve_commit_sha(tmp_path / "checkout")

    asyncio.run(scenario())
    child_path = record_path.with_suffix(".child")
    _wait_for_process_exit(int(child_path.read_text(encoding="ascii")))


def test_real_metadata_cancellation_terminates_process_tree(tmp_path: Path) -> None:
    client, record_path = _stub_client(tmp_path, mode="metadata-cancel")

    async def scenario() -> None:
        task = asyncio.create_task(client.resolve_commit_sha(tmp_path / "checkout"))
        await asyncio.to_thread(_wait_for_file, record_path.with_suffix(".child"))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    _wait_for_process_exit(int(record_path.with_suffix(".child").read_text(encoding="ascii")))


def test_service_metadata_cancellation_cleans_workspace_and_yields_no_snapshot(
    tmp_path: Path,
) -> None:
    client, record_path = _stub_client(tmp_path, mode="metadata-cancel")
    created_directories: list[Path] = []

    def create_temporary_directory(prefix: str) -> str:
        directory = tempfile.mkdtemp(prefix=prefix)
        created_directories.append(Path(directory))
        return directory

    service = RepositoryIngestionService(
        git_client=client,
        resolve_addresses=lambda _hostname: ["93.184.216.34"],
        temporary_directory_factory=create_temporary_directory,
    )
    cancellation_event = asyncio.Event()
    yielded = False

    async def scenario() -> None:
        nonlocal yielded
        with pytest.raises(RepositoryCancelledError):
            async with service.ingest(_PUBLIC_TEST_URL, cancellation_event=cancellation_event):
                yielded = True

    async def run_and_cancel() -> None:
        task = asyncio.create_task(scenario())
        await asyncio.to_thread(_wait_for_file, record_path.with_suffix(".child"))
        cancellation_event.set()
        await task

    asyncio.run(run_and_cancel())
    assert not yielded
    assert created_directories
    assert all(not directory.exists() for directory in created_directories)
    _wait_for_process_exit(int(record_path.with_suffix(".child").read_text(encoding="ascii")))


def test_real_clone_discards_large_git_output_and_uses_monitor_interval(tmp_path: Path) -> None:
    client, _record_path = _stub_client(tmp_path, mode="output")

    async def scenario() -> None:
        await client.clone(
            _public_target(),
            tmp_path / "checkout",
            1,
            1_000_000,
            100,
            None,
            monitor_interval_seconds=0.001,
        )

    asyncio.run(scenario())


def test_metadata_output_is_bounded(tmp_path: Path) -> None:
    client, _record_path = _stub_client(tmp_path, mode="metadata-output")

    async def scenario() -> None:
        with pytest.raises(RepositoryOutputLimitError):
            await client.resolve_commit_sha(tmp_path / "checkout")

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", [RecursionError(), PermissionError("denied")])
def test_traversal_failures_are_explicit_domain_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    def failing_iter(_root: Path, *, include_git: bool) -> Iterator[Path]:
        del include_git
        raise failure

    monkeypatch.setattr(ingestion, "_iter_files", failing_iter)

    with pytest.raises(RepositoryInspectionError):
        ingestion._measure_storage(tmp_path)


def test_real_metadata_errors_are_explicit(tmp_path: Path) -> None:
    client, _record_path = _stub_client(tmp_path, mode="failure")

    async def scenario() -> None:
        with pytest.raises(RepositoryInspectionError):
            await client.resolve_commit_sha(tmp_path / "checkout")

    asyncio.run(scenario())


def test_real_metadata_accepts_sha256_commit_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _record_path = _stub_client(tmp_path)
    monkeypatch.setenv("STUB_SHA", "b" * 64)

    async def scenario() -> None:
        assert await client.resolve_commit_sha(tmp_path / "checkout") == "b" * 64

    asyncio.run(scenario())


def test_process_termination_failure_is_an_explicit_domain_error() -> None:
    assert issubclass(RepositoryProcessTerminationError, RepositoryIngestionError)
    assert issubclass(RepositoryMetadataError, RepositoryIngestionError)
