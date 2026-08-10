from __future__ import annotations

# This fixture invokes only test-owned Git commands.
import subprocess  # nosec B404
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codepilot.analyzers.git_history import GitHistoryConfig, GitHistoryService


def _git(repo: Path, *args: str) -> None:
    # The helper is test-owned and receives only fixed Git arguments from isolated fixtures.
    subprocess.run(  # nosec B603, B607
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


def _commit(repo: Path, message: str, author: str) -> None:
    name, email = author.split(" <")
    email = email.rstrip(">")
    _git(repo, "config", "user.name", name)
    _git(repo, "config", "user.email", email)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message, "--author", f"{name} <{email}>")


def test_git_history_metrics_and_hotspots_are_explainable(tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch", "main")
    source = tmp_path / "hot.py"
    source.write_text("x = 1\n", encoding="utf-8")
    _commit(tmp_path, "initial", "Alice <alice@example.test>")
    source.write_text("x = 1\n" + "y = 2\n" * 5, encoding="utf-8")
    _commit(tmp_path, "change", "Bob <bob@example.test>")
    (tmp_path / "stable.py").write_text("x = 1\n", encoding="utf-8")
    _commit(tmp_path, "stable", "Bob <bob@example.test>")

    metrics = GitHistoryService(
        GitHistoryConfig(max_commits=20, window_days=3650),
    ).collect(
        tmp_path,
        now=datetime.now(UTC),
        complexity_by_path={"hot.py": 20, "stable.py": 1},
        finding_density_by_path={"hot.py": 3, "stable.py": 0},
    )

    hot = metrics.by_path["hot.py"]
    assert hot.commit_count == 2
    assert hot.author_count == 2
    assert hot.recent_churn > metrics.by_path["stable.py"].recent_churn
    assert metrics.top_hotspots(1)[0].path == "hot.py"
    assert "complexity" in hot.score_explanation


def test_git_history_respects_commit_limit(tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch", "main")
    source = tmp_path / "app.py"
    for index in range(3):
        source.write_text(f"value = {index}\n", encoding="utf-8")
        _commit(tmp_path, str(index), "Alice <alice@example.test>")

    metrics = GitHistoryService(GitHistoryConfig(max_commits=2)).collect(tmp_path)
    assert metrics.by_path["app.py"].commit_count == 2


def test_invalid_history_limits_are_rejected() -> None:
    with pytest.raises(ValueError):
        GitHistoryConfig(max_commits=0)
    with pytest.raises(ValueError):
        GitHistoryConfig(window_days=0)


def test_git_history_keeps_repository_path_out_of_git_arguments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[tuple[str, ...], Path]] = []

    def fake_run(command: tuple[str, ...], *, cwd: Path, **_kwargs: object) -> object:
        calls.append((command, cwd))
        return type("Completed", (), {"stdout": ""})()

    monkeypatch.setattr("codepilot.analyzers.git_history.subprocess.run", fake_run)

    GitHistoryService().collect(tmp_path)

    assert calls
    command, cwd = calls[0]
    assert cwd == tmp_path
    assert command[-2:] == ("--", ".")
    assert str(tmp_path) not in command
