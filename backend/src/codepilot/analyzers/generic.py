"""Deterministic generic analyzers that only inspect repository bytes."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from codepilot.analyzers.framework import (
    AnalyzerContext,
    AnalyzerMetadata,
    AnalyzerMetrics,
    AnalyzerResult,
    NormalizedFinding,
)

_IGNORED_DIRECTORIES = frozenset({".git", ".hg", ".svn", "node_modules", "vendor", "dist", "build"})
_SOURCE_SUFFIXES = frozenset(
    {".c", ".cpp", ".cs", ".go", ".h", ".java", ".js", ".jsx", ".py", ".rs", ".ts", ".tsx"}
)
_GENERATED_MARKERS = (".generated.", ".g.", ".designer.", ".min.")


def _iter_source_files(root: Path) -> Iterator[tuple[Path, int]]:
    excluded = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts
        if any(part in _IGNORED_DIRECTORIES for part in relative_parts):
            excluded += 1
            continue
        if any(marker in path.name.lower() for marker in _GENERATED_MARKERS):
            excluded += 1
            continue
        if path.suffix.lower() not in _SOURCE_SUFFIXES:
            excluded += 1
            continue
        yield path, excluded
        excluded = 0


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


class LargeSourceFileAnalyzer:
    metadata = AnalyzerMetadata(
        name="generic.large-source-file",
        version="1.0.0",
        supported_languages=frozenset(
            {"c", "cpp", "csharp", "go", "java", "javascript", "python", "rust", "typescript"}
        ),
        capabilities=frozenset({"quality"}),
    )

    def __init__(self, max_source_bytes: int = 1_000_000) -> None:
        self._max_source_bytes = max_source_bytes

    async def analyze(self, context: AnalyzerContext) -> AnalyzerResult:
        findings: list[NormalizedFinding] = []
        files = 0
        excluded = 0
        for path, skipped in _iter_source_files(context.repository_path):
            files += 1
            excluded += skipped
            if path.stat().st_size > self._max_source_bytes:
                findings.append(
                    NormalizedFinding(
                        analyzer=self.metadata.name,
                        rule_id="GEN001",
                        severity="warning",
                        category="maintainability",
                        title="Large source file",
                        description="Source file exceeds the configured size threshold.",
                        path=_relative(path, context.repository_path),
                        start_line=1,
                        end_line=1,
                        remediation="Split the file into cohesive modules.",
                    )
                )
        return AnalyzerResult(
            findings=tuple(findings), metrics=AnalyzerMetrics(files, excluded_files=excluded)
        )


class LongLineAnalyzer:
    metadata = AnalyzerMetadata(
        name="generic.long-line",
        version="1.0.0",
        supported_languages=LargeSourceFileAnalyzer.metadata.supported_languages,
        capabilities=frozenset({"quality"}),
    )

    def __init__(self, max_line_length: int = 120) -> None:
        self._max_line_length = max_line_length

    async def analyze(self, context: AnalyzerContext) -> AnalyzerResult:
        findings: list[NormalizedFinding] = []
        for path, _ in _iter_source_files(context.repository_path):
            raw = path.read_bytes()
            if b"\x00" in raw:
                continue
            text = raw.decode("utf-8", errors="replace")
            for line_number, line in enumerate(text.splitlines(), start=1):
                if len(line) > self._max_line_length:
                    findings.append(
                        NormalizedFinding(
                            analyzer=self.metadata.name,
                            rule_id="GEN002",
                            severity="info",
                            category="style",
                            title="Excessively long line",
                            description="Line exceeds the configured length threshold.",
                            path=_relative(path, context.repository_path),
                            start_line=line_number,
                            end_line=line_number,
                            evidence=line[: self._max_line_length],
                            remediation="Wrap the line or extract a named value.",
                        )
                    )
        return AnalyzerResult(findings=tuple(findings))


class BasicFileMetricsAnalyzer:
    metadata = AnalyzerMetadata(
        name="generic.file-metrics",
        version="1.0.0",
        supported_languages=frozenset(),
        capabilities=frozenset({"metrics", "exclusion-verification"}),
    )

    async def analyze(self, context: AnalyzerContext) -> AnalyzerResult:
        files = 0
        lines = 0
        excluded = 0
        for path, skipped in _iter_source_files(context.repository_path):
            files += 1
            excluded += skipped
            raw = path.read_bytes()
            if b"\x00" not in raw:
                lines += raw.count(b"\n") + (1 if raw and not raw.endswith(b"\n") else 0)
        return AnalyzerResult(metrics=AnalyzerMetrics(files, lines, excluded))
