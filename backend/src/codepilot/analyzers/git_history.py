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
        cutoff = current - timedelta(days=self._config.window_days)
        commits: dict[str, list[tuple[datetime, str, int]]] = defaultdict(list)
        for commit_date, author, additions, deletions, path in _parse_log(completed.stdout):
            if commit_date < cutoff:
                continue
            commits[path].append((commit_date, author, additions + deletions))
        complexity = complexity_by_path or {}
        finding_density = finding_density_by_path or {}
        metrics: dict[str, FileHistoryMetric] = {}
        for path, entries in commits.items():
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
            metrics[path] = FileHistoryMetric(
                path=path,
                commit_count=len(entries),
                recent_change_frequency=len(entries) / self._config.window_days,
                author_count=len(authors),
                ownership_concentration=max(authors.values()) / len(entries),
                file_age_days=age,
                recent_churn=churn,
                complexity=path_complexity,
                finding_density=path_density,
                hotspot_score=score,
                score_explanation=(
                    f"complexity={path_complexity:.2f}*0.50; "
                    f"recent_churn={churn}*0.30; finding_density={path_density:.2f}*0.20"
                ),
            )
        return GitHistoryMetrics(metrics)


def _parse_log(output: str) -> list[tuple[datetime, str, int, int, str]]:
    parsed: list[tuple[datetime, str, int, int, str]] = []
    for record in output.split("\x1e"):
        if not record.strip():
            continue
        lines = record.splitlines()
        if not lines or "\x1f" not in lines[0]:
            continue
        date_text, author = lines[0].split("\x1f", 1)
        try:
            commit_date = datetime.fromisoformat(date_text).astimezone(UTC)
        except ValueError:
            continue
        for line in lines[1:]:
            parts = line.split("\t", 2)
            if len(parts) != 3 or not parts[2]:
                continue
            additions = 0 if parts[0] == "-" else int(parts[0])
            deletions = 0 if parts[1] == "-" else int(parts[1])
            parsed.append((commit_date, author, additions, deletions, _normalize_rename(parts[2])))
    return parsed


def _normalize_rename(path: str) -> str:
    if "{" in path and " => " in path and "}" in path:
        prefix, rest = path.split("{", 1)
        middle, suffix = rest.split("}", 1)
        _old, new = middle.split(" => ", 1)
        return f"{prefix}{new}{suffix}".replace("\\", "/")
    if " => " in path:
        return path.split(" => ", 1)[1].replace("\\", "/")
    return path.replace("\\", "/")
