from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from codepilot.analyzers.production import ProductionRepositoryAnalyzer
from codepilot.analyzers.python_adapters import SubprocessToolRunner, ToolExecution, ToolResult
from codepilot.services.repository_ingestion import RepositorySnapshot


def test_production_analyzer_runs_generic_and_python_tools(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    snapshot = RepositorySnapshot(tmp_path, "a" * 40, "main", ("Python",), 1, 6)
    analyzer = ProductionRepositoryAnalyzer(tool_timeout_seconds=1)
    result = asyncio.run(analyzer.analyze(snapshot))
    assert result.analyzed_file_count == 1
    assert result.source_lines == 1
    assert result.analyzer_outcomes
    assert any(item.analyzer == "generic.file-metrics" for item in result.analyzer_outcomes)


def test_production_analyzer_requires_language_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def unavailable_tool(
        _self: SubprocessToolRunner,
        executable: str,
        _args: tuple[str, ...],
        _cwd: Path,
        _timeout_seconds: float,
    ) -> ToolResult:
        return ToolResult(
            -1,
            "",
            f"{executable} is not installed.",
            ToolExecution(executable, None, 0.0, False),
        )

    monkeypatch.setattr(SubprocessToolRunner, "run", unavailable_tool)
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    snapshot = RepositorySnapshot(tmp_path, "a" * 40, "main", ("Python",), 1, 6)
    analyzer = ProductionRepositoryAnalyzer(tool_timeout_seconds=1)
    result = asyncio.run(analyzer.analyze(snapshot))
    assert result.analyzer_outcomes
    assert result.execution_succeeded is False


def test_generic_only_repository_can_complete_cleanly(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("clean\n", encoding="utf-8")
    snapshot = RepositorySnapshot(tmp_path, "a" * 40, "main", (), 1, 6)
    result = asyncio.run(ProductionRepositoryAnalyzer().analyze(snapshot))

    assert result.findings == ()
    assert result.source_lines == 0
    assert result.execution_succeeded is True
