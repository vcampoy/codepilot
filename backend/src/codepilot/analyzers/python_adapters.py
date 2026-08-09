"""Adapters for deterministic Python tooling with machine-readable output."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import Awaitable
from pathlib import Path
from typing import Protocol

from codepilot.analyzers.framework import (
    AnalyzerContext,
    AnalyzerExecution,
    AnalyzerMetadata,
    AnalyzerMetrics,
    AnalyzerResult,
    NormalizedFinding,
)

ToolExecution = AnalyzerExecution


class ToolResult:
    """Result returned by a tool runner."""

    def __init__(
        self,
        returncode: int,
        stdout: str,
        stderr: str,
        execution: ToolExecution,
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.execution = execution


class ToolRunner(Protocol):
    def run(
        self,
        executable: str,
        args: tuple[str, ...],
        cwd: Path,
        timeout_seconds: float,
    ) -> Awaitable[ToolResult]: ...


class SubprocessToolRunner:
    """Run fixed external tool arguments without invoking a shell."""

    async def run(
        self,
        executable: str,
        args: tuple[str, ...],
        cwd: Path,
        timeout_seconds: float,
    ) -> ToolResult:
        started = time.perf_counter()
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["PYTHONNOUSERSITE"] = "1"
        try:
            process = await asyncio.create_subprocess_exec(
                executable,
                *args,
                cwd=str(cwd),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout_seconds
                )
            except TimeoutError:
                process.kill()
                await process.wait()
                return ToolResult(
                    -1,
                    "",
                    "Tool execution timed out.",
                    ToolExecution(executable, None, time.perf_counter() - started, True),
                )
        except FileNotFoundError:
            return ToolResult(
                -1,
                "",
                f"{executable} is not installed.",
                ToolExecution(executable, None, time.perf_counter() - started, False),
            )
        return ToolResult(
            process.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
            ToolExecution(
                executable,
                _version_from_text(stdout.decode()),
                time.perf_counter() - started,
                True,
            ),
        )


def _version_from_text(value: str) -> str | None:
    match = re.search(r"\d+(?:\.\d+)+(?:[-+][\w.-]+)?", value)
    return match.group(0) if match else None


def _path(value: str, root: Path) -> str:
    candidate = Path(value)
    try:
        return candidate.relative_to(root).as_posix()
    except ValueError:
        return candidate.as_posix()


def _severity(code: str) -> str:
    if code.startswith(("E", "F", "B")):
        return "error"
    return "warning" if code.startswith("W") else "info"


def parse_ruff_json(payload: str, root: Path | None = None) -> tuple[NormalizedFinding, ...]:
    values = json.loads(payload)
    return tuple(
        NormalizedFinding(
            analyzer="python.ruff",
            rule_id=str(value["code"]),
            severity=_severity(str(value["code"])),
            category="security" if str(value["code"]).startswith("B") else "quality",
            title=str(value["code"]),
            description=str(value["message"]),
            path=_path(str(value["filename"]), root)
            if root
            else Path(str(value["filename"])).as_posix(),
            start_line=int(value["location"]["row"]),
            end_line=int(value.get("end_location", value["location"])["row"]),
        )
        for value in values
    )


def parse_bandit_json(payload: str, root: Path | None = None) -> tuple[NormalizedFinding, ...]:
    values = json.loads(payload).get("results", [])
    severity_map = {"LOW": "info", "MEDIUM": "warning", "HIGH": "error"}
    findings: list[NormalizedFinding] = []
    for value in values:
        path = (
            _path(str(value["filename"]), root)
            if root
            else Path(str(value["filename"])).as_posix()
        )
        rule_id = str(value["test_id"])
        if rule_id == "B101" and _is_pytest_path(path):
            continue
        findings.append(
            NormalizedFinding(
                analyzer="python.bandit",
                rule_id=rule_id,
                severity=severity_map.get(str(value["issue_severity"]).upper(), "warning"),
                category="security",
                title=rule_id,
                description=str(value["issue_text"]),
                path=path,
                start_line=int(value["line_number"]),
                end_line=int(value.get("line_range", [value["line_number"]])[-1]),
            )
        )
    return tuple(findings)


def _is_pytest_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.startswith(("backend/tests/", "tests/")) and normalized.endswith(".py")


def parse_radon_cc_json(
    payload: str, root: Path | None = None
) -> tuple[tuple[NormalizedFinding, ...], int]:
    values = json.loads(payload)
    findings: list[NormalizedFinding] = []
    maximum = 0
    for filename, blocks in values.items():
        for block in blocks:
            complexity = int(block["complexity"])
            maximum = max(maximum, complexity)
            if complexity >= 10:
                findings.append(
                    NormalizedFinding(
                        analyzer="python.radon",
                        rule_id="RADON-CC",
                        severity="warning" if complexity < 15 else "error",
                        category="complexity",
                        title="High cyclomatic complexity",
                        description=f"{block['name']} has cyclomatic complexity {complexity}.",
                        path=_path(str(filename), root) if root else Path(str(filename)).as_posix(),
                        start_line=int(block["lineno"]),
                        end_line=int(block.get("endline", block["lineno"])),
                    )
                )
    return tuple(findings), maximum


def parse_radon_mi_json(payload: str) -> float | None:
    values = json.loads(payload)
    scores = [float(value["mi"]) for value in values.values() if "mi" in value]
    return min(scores) if scores else None


class _PythonToolAnalyzer:
    executable: str
    metadata: AnalyzerMetadata

    def __init__(self, runner: ToolRunner | None = None, timeout_seconds: float = 60.0) -> None:
        self._runner = runner or SubprocessToolRunner()
        self._timeout_seconds = timeout_seconds

    async def _run_tool(
        self, context: AnalyzerContext, args: tuple[str, ...]
    ) -> tuple[ToolResult, ToolResult]:
        version = await self._runner.run(
            self.executable, ("--version",), context.repository_path, self._timeout_seconds
        )
        scan = await self._runner.run(
            self.executable, args, context.repository_path, self._timeout_seconds
        )
        return version, scan

    def _execution(self, version: ToolResult, scan: ToolResult, started: float) -> ToolExecution:
        return ToolExecution(
            self.executable,
            version.execution.version or scan.execution.version,
            time.perf_counter() - started,
            version.execution.available and scan.execution.available,
            scan.stderr or version.stderr or None,
        )


class RuffAnalyzer(_PythonToolAnalyzer):
    executable = "ruff"
    metadata = AnalyzerMetadata(
        name="python.ruff",
        version="external",
        supported_languages=frozenset({"python"}),
        capabilities=frozenset({"lint"}),
    )

    async def analyze(self, context: AnalyzerContext) -> AnalyzerResult:
        started = time.perf_counter()
        version, scan = await self._run_tool(
            context, ("check", ".", "--output-format", "json", "--no-cache", "--isolated")
        )
        execution = self._execution(version, scan, started)
        if not execution.available:
            return AnalyzerResult(execution=execution)
        return AnalyzerResult(
            findings=parse_ruff_json(scan.stdout, context.repository_path), execution=execution
        )


class BanditAnalyzer(_PythonToolAnalyzer):
    executable = "bandit"
    metadata = AnalyzerMetadata(
        name="python.bandit",
        version="external",
        supported_languages=frozenset({"python"}),
        capabilities=frozenset({"security"}),
    )

    async def analyze(self, context: AnalyzerContext) -> AnalyzerResult:
        started = time.perf_counter()
        version, scan = await self._run_tool(context, ("-r", ".", "-f", "json", "-q"))
        execution = self._execution(version, scan, started)
        if not execution.available:
            return AnalyzerResult(execution=execution)
        return AnalyzerResult(
            findings=parse_bandit_json(scan.stdout, context.repository_path), execution=execution
        )


class RadonAnalyzer(_PythonToolAnalyzer):
    executable = "radon"
    metadata = AnalyzerMetadata(
        name="python.radon",
        version="external",
        supported_languages=frozenset({"python"}),
        capabilities=frozenset({"complexity", "maintainability"}),
    )

    async def analyze(self, context: AnalyzerContext) -> AnalyzerResult:
        started = time.perf_counter()
        version, cc = await self._run_tool(context, ("cc", ".", "-j"))
        _, mi = await self._run_tool(context, ("mi", ".", "-j"))
        execution = self._execution(version, cc, started)
        if not execution.available:
            return AnalyzerResult(execution=execution)
        findings, complexity = parse_radon_cc_json(cc.stdout, context.repository_path)
        return AnalyzerResult(
            findings=findings,
            metrics=AnalyzerMetrics(
                cyclomatic_complexity=complexity,
                maintainability_index=parse_radon_mi_json(mi.stdout),
            ),
            execution=execution,
        )
