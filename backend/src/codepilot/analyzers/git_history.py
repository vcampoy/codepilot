"""Bounded, local Git history metrics and explainable hotspot scoring."""

from __future__ import annotations

import subprocess
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol


class GitHistoryError(RuntimeError):
    """Git history could not be collected safely."""


@dataclass(frozen=True, slots=True)
class GitHistoryConfig:
    window_days: int = 365
    max_commits: int = 5_000
    timeout_seconds: float = 30.0
    max_output_bytes: int = 20_000_000

    def __post_init__(self) -> None:
        if self.window_days <= 0 or self.max_commits <= 0:
            raise ValueError("window_days and max_commits must be positive")
        if self.timeout_seconds <= 0 or self.max_output_bytes <= 0:
            raise ValueError("timeout_seconds and max_output_bytes must be positive")


@dataclass(frozen=True, slots=True)
class FileHistoryMetric:
    path: str
    commit_count: int
    recent_change_frequency: float
    author_count: int
    ownership_concentration: float
    file_age_days: float
    recent_churn: int
    complexity: float
    finding_density: float
    hotspot_score: float
    score_explanation: str


@dataclass(frozen=True, slots=True)
class GitHistoryMetrics:
    by_path: dict[str, FileHistoryMetric]

    def top_hotspots(self, limit: int = 10) -> tuple[FileHistoryMetric, ...]:
        if limit <= 0:
            return ()
        return tuple(
            sorted(
                self.by_path.values(),
                key=lambda metric: (-metric.hotspot_score, metric.path),
            )[:limit]
        )


class HistoryMetricStore(Protocol):
    """Minimal persistence seam for attaching metrics to an analysis."""

    def save(self, analysis_id: str, metrics: GitHistoryMetrics) -> None: ...

    def get(self, analysis_id: str) -> GitHistoryMetrics | None: ...


class InMemoryHistoryMetricStore:
    def __init__(self) -> None:
        self._values: dict[str, GitHistoryMetrics] = {}

    def save(self, analysis_id: str, metrics: GitHistoryMetrics) -> None:
        self._values[analysis_id] = metrics

    def get(self, analysis_id: str) -> GitHistoryMetrics | None:
        return self._values.get(analysis_id)


class GitHistoryService:
    """Collect rename-aware-enough metrics using bounded local Git history."""

    def __init__(self, config: GitHistoryConfig | None = None) -> None:
        self._config = config or GitHistoryConfig()

    def collect(
        self,
        repository_path: Path,
        *,
        now: datetime | None = None,
        complexity_by_path: Mapping[str, float] | None = None,
        finding_density_by_path: Mapping[str, float] | None = None,
    ) -> GitHistoryMetrics:
        current = now or datetime.now(UTC)
        output = self._run_log(repository_path)
        cutoff = current - timedelta(days=self._config.window_days)
        commits = _group_recent_commits(_parse_log(output), cutoff)
        return GitHistoryMetrics(
            _build_history_metrics(
                commits,
                current,
                self._config,
                complexity_by_path or {},
                finding_density_by_path or {},
            )
        )

    def _run_log(self, repository_path: Path) -> str:
        command = [
            "git",
            "log",
            "--numstat",
            "--date=iso-strict",
            "--format=%x1e%aI%x1f%an",
            "--all",
            "-M",
            f"--max-count={self._config.max_commits}",
            "--",
            ".",
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=repository_path,
                check=True,
                capture_output=True,
                text=True,
                timeout=self._config.timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise GitHistoryError("Git history collection failed.") from error
        if len(completed.stdout.encode("utf-8")) > self._config.max_output_bytes:
            raise GitHistoryError("Git history output exceeded the configured limit.")
        return completed.stdout


def _parse_log(output: str) -> list[tuple[datetime, str, int, int, str]]:
    parsed: list[tuple[datetime, str, int, int, str]] = []
    for record in output.split("\x1e"):
        header, numstat_lines = _split_log_record(record)
        if header is None:
            continue
        date_text, author = header
        try:
            commit_date = datetime.fromisoformat(date_text).astimezone(UTC)
        except ValueError:
            continue
        parsed.extend(_parse_numstat_lines(commit_date, author, numstat_lines))
    return parsed


def _split_log_record(record: str) -> tuple[tuple[str, str] | None, list[str]]:
    if not record.strip():
        return None, []
    lines = record.splitlines()
    if not lines or "\x1f" not in lines[0]:
        return None, []
    date_text, author = lines[0].split("\x1f", 1)
    return (date_text, author), lines[1:]


def _parse_numstat_lines(
    commit_date: datetime, author: str, lines: list[str]
) -> list[tuple[datetime, str, int, int, str]]:
    parsed: list[tuple[datetime, str, int, int, str]] = []
    for line in lines:
        parts = line.split("\t", 2)
        if len(parts) != 3 or not parts[2]:
            continue
        try:
            additions = 0 if parts[0] == "-" else int(parts[0])
            deletions = 0 if parts[1] == "-" else int(parts[1])
        except ValueError:
            continue
        parsed.append((commit_date, author, additions, deletions, _normalize_rename(parts[2])))
    return parsed


def _group_recent_commits(
    entries: list[tuple[datetime, str, int, int, str]], cutoff: datetime
) -> dict[str, list[tuple[datetime, str, int]]]:
    commits: dict[str, list[tuple[datetime, str, int]]] = defaultdict(list)
    for commit_date, author, additions, deletions, path in entries:
        if commit_date >= cutoff:
            commits[path].append((commit_date, author, additions + deletions))
    return commits


def _build_history_metrics(
    commits: dict[str, list[tuple[datetime, str, int]]],
    current: datetime,
    config: GitHistoryConfig,
    complexity: Mapping[str, float],
    finding_density: Mapping[str, float],
) -> dict[str, FileHistoryMetric]:
    return {
        path: _metric_for_path(path, entries, current, config, complexity, finding_density)
        for path, entries in commits.items()
    }


def _metric_for_path(
    path: str,
    entries: list[tuple[datetime, str, int]],
    current: datetime,
    config: GitHistoryConfig,
    complexity: Mapping[str, float],
    finding_density: Mapping[str, float],
) -> FileHistoryMetric:
    authors = Counter(entry[1] for entry in entries)
    churn = sum(entry[2] for entry in entries)
    age = max((current - min(entry[0] for entry in entries)).total_seconds() / 86400, 0)
    path_complexity = float(complexity.get(path, 0))
    path_density = float(finding_density.get(path, 0))
    score = (
        min(path_complexity / 20, 1.0) * 0.5
        + min(churn / 100, 1.0) * 0.3
        + min(path_density / 10, 1.0) * 0.2
    )
    return FileHistoryMetric(
        path,
        len(entries),
        len(entries) / config.window_days,
        len(authors),
        max(authors.values()) / len(entries),
        age,
        churn,
        path_complexity,
        path_density,
        score,
        (
            f"complexity={path_complexity:.2f}*0.50; recent_churn={churn}*0.30; "
            f"finding_density={path_density:.2f}*0.20"
        ),
    )


def _normalize_rename(path: str) -> str:
    if "{" in path and " => " in path and "}" in path:
        prefix, rest = path.split("{", 1)
        middle, suffix = rest.split("}", 1)
        _old, new = middle.split(" => ", 1)
        return f"{prefix}{new}{suffix}".replace("\\", "/")
    if " => " in path:
        return path.split(" => ", 1)[1].replace("\\", "/")
    return path.replace("\\", "/")
