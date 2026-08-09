"""ESLint and SARIF adapters for language-neutral analysis results."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from codepilot.analyzers.framework import (
    AnalyzerContext,
    AnalyzerExecution,
    AnalyzerMetadata,
    AnalyzerResult,
    NormalizedFinding,
)
from codepilot.analyzers.python_adapters import (
    ToolRunner,
    _PythonToolAnalyzer,
)


def parse_eslint_json(payload: str, root: Path | None = None) -> tuple[NormalizedFinding, ...]:
    """Parse ESLint's JSON formatter without importing project configuration."""
    values = json.loads(payload)
    findings: list[NormalizedFinding] = []
    for file_result in values:
        raw_path = str(file_result.get("filePath", "<unknown>"))
        path = raw_path if root is None else _relative_tool_path(raw_path, root)
        for message in file_result.get("messages", []):
            rule_id = str(message.get("ruleId") or "ESLint")
            severity_value = int(message.get("severity", 1))
            severity = "error" if severity_value >= 2 else "warning"
            start_line = int(message.get("line") or 1)
            findings.append(
                NormalizedFinding(
                    analyzer="javascript.eslint",
                    rule_id=rule_id,
                    severity=severity,
                    category="quality",
                    title=rule_id,
                    description=str(message.get("message", "ESLint finding")),
                    path=path,
                    start_line=start_line,
                    end_line=int(message.get("endLine") or start_line),
                )
            )
    return tuple(findings)


def _relative_tool_path(value: str, root: Path) -> str:
    candidate = Path(value)
    try:
        return candidate.relative_to(root).as_posix()
    except ValueError:
        return candidate.as_posix()


class EslintAnalyzer(_PythonToolAnalyzer):
    """Run an already-installed ESLint executable; never install dependencies."""

    executable = "eslint"
    config_path = "/opt/codepilot/analyzer-runtime/eslint.config.mjs"
    metadata = AnalyzerMetadata(
        name="javascript.eslint",
        version="external",
        supported_languages=frozenset({"javascript", "typescript"}),
        capabilities=frozenset({"lint"}),
    )

    def __init__(self, runner: ToolRunner | None = None, timeout_seconds: float = 60.0) -> None:
        super().__init__(runner=runner, timeout_seconds=timeout_seconds)

    async def analyze(self, context: AnalyzerContext) -> AnalyzerResult:
        started = time.perf_counter()
        version, scan = await self._run_tool(
            context,
            (
                ".",
                "--format",
                "json",
                "--config",
                self.config_path,
                "--no-config-lookup",
                "--no-error-on-unmatched-pattern",
            ),
        )
        execution = self._execution(version, scan, started)
        if not execution.available:
            return AnalyzerResult(execution=execution)
        return AnalyzerResult(
            findings=parse_eslint_json(scan.stdout, context.repository_path), execution=execution
        )


class SarifTooLargeError(ValueError):
    """The uploaded SARIF document exceeded its configured byte limit."""


class SarifTooDeepError(ValueError):
    """The uploaded SARIF document exceeded its configured nesting limit."""


def _check_depth(value: object, depth: int, maximum: int) -> None:
    if depth > maximum:
        raise SarifTooDeepError("SARIF nesting depth exceeds the configured limit.")
    if isinstance(value, dict):
        for child in value.values():
            _check_depth(child, depth + 1, maximum)
    elif isinstance(value, list):
        for child in value:
            _check_depth(child, depth + 1, maximum)


def _load_sarif_document(payload: str | bytes, max_bytes: int, max_depth: int) -> dict[str, Any]:
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    if len(raw) > max_bytes:
        raise SarifTooLargeError("SARIF document exceeds the configured size limit.")
    document = json.loads(raw)
    _check_depth(document, 0, max_depth)
    if not isinstance(document, dict):
        raise ValueError("SARIF document must be a JSON object.")
    if document.get("version") != "2.1.0" or not isinstance(document.get("runs"), list):
        raise ValueError("SARIF document must use version 2.1.0 and contain runs.")
    return document


def _parse_sarif_result(result: dict[str, Any], analyzer: str) -> NormalizedFinding:
    artifact, region = _sarif_location(result)
    start_line = _sarif_start_line(region)
    return NormalizedFinding(
        analyzer=analyzer,
        rule_id=str(result.get("ruleId") or "SARIF"),
        severity=_sarif_severity(result),
        category=_sarif_category(analyzer),
        title=str(result.get("ruleId") or "SARIF finding"),
        description=str(result.get("message", {}).get("text", "SARIF finding")),
        path=Path(str(artifact.get("uri") or "<unknown>")).as_posix(),
        start_line=start_line,
        end_line=_sarif_end_line(region, start_line),
        evidence=_sarif_evidence(result),
    )


def _sarif_location(result: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    location = (result.get("locations") or [{}])[0].get("physicalLocation", {})
    return location.get("artifactLocation", {}), location.get("region", {})


def _sarif_start_line(region: dict[str, Any]) -> int:
    return int(region.get("startLine") or 1)


def _sarif_end_line(region: dict[str, Any], start_line: int) -> int:
    return int(region.get("endLine") or start_line)


def _sarif_severity(result: dict[str, Any]) -> str:
    return {"error": "error", "warning": "warning", "note": "info"}.get(
        str(result.get("level", "warning")), "info"
    )


def _sarif_category(analyzer: str) -> str:
    return "security" if analyzer.casefold() == "roslyn" else "quality"


def _sarif_evidence(result: dict[str, Any]) -> str | None:
    return str((result.get("fingerprints") or {}).get("primaryLocationLineHash", "")) or None


def _parse_sarif_run(run: dict[str, Any]) -> tuple[NormalizedFinding, ...]:
    driver = run.get("tool", {}).get("driver", {})
    analyzer = str(driver.get("name") or "SARIF")
    return tuple(_parse_sarif_result(result, analyzer) for result in run.get("results", []))


def parse_sarif_json(
    payload: str | bytes,
    *,
    max_bytes: int = 5_000_000,
    max_depth: int = 50,
) -> tuple[NormalizedFinding, ...]:
    """Parse SARIF 2.1 results with bounded size and nesting."""
    document = _load_sarif_document(payload, max_bytes, max_depth)
    return tuple(finding for run in document["runs"] for finding in _parse_sarif_run(run))


class SarifFileAnalyzer:
    """Import an existing SARIF artifact without running a build or repository code."""

    metadata = AnalyzerMetadata(
        name="sarif.import",
        version="2.1.0",
        supported_languages=frozenset(),
        capabilities=frozenset({"import"}),
    )

    def __init__(self, sarif_path: Path, max_bytes: int = 5_000_000) -> None:
        self._path = sarif_path
        self._max_bytes = max_bytes

    async def analyze(self, context: AnalyzerContext) -> AnalyzerResult:
        del context
        started = time.perf_counter()
        raw = self._path.read_bytes()
        findings = parse_sarif_json(raw, max_bytes=self._max_bytes)
        return AnalyzerResult(
            findings=findings,
            execution=AnalyzerExecution(
                "sarif-import", "2.1.0", time.perf_counter() - started, True
            ),
        )
