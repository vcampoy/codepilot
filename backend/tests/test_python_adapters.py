from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Final

from codepilot.analyzers.framework import AnalyzerContext
from codepilot.analyzers.python_adapters import (
    BanditAnalyzer,
    RadonAnalyzer,
    RuffAnalyzer,
    ToolExecution,
    ToolResult,
    parse_bandit_json,
    parse_radon_cc_json,
    parse_ruff_json,
)

_BANDIT_POLICY_PAYLOAD: Final = json.dumps(
    {
        "results": [
            {
                "test_id": "B101",
                "issue_text": "Use of assert",
                "issue_severity": "LOW",
                "filename": "backend/tests/test_policy.py",
                "line_number": 1,
            },
            {
                "test_id": "B101",
                "issue_text": "Use of assert",
                "issue_severity": "LOW",
                "filename": "backend/src/codepilot/policy.py",
                "line_number": 2,
            },
        ]
    }
)
_EXPECTED_RUFF_SOURCE_ROOTS: Final[tuple[tuple[str, str], ...]] = (
    ("backend/src", "codepilot"),
    ("packages/src", "widgets"),
)


def test_bandit_policy_excludes_backend_pytest_asserts_but_keeps_production() -> None:
    findings = parse_bandit_json(_BANDIT_POLICY_PAYLOAD, Path("."))

    assert [(finding.rule_id, finding.path, finding.start_line) for finding in findings] == [
        ("B101", "backend/src/codepilot/policy.py", 2)
    ]


def test_bandit_policy_excludes_backend_root_pytest_asserts_but_keeps_production() -> None:
    payload = json.dumps(
        {
            "results": [
                {
                    "test_id": "B101",
                    "issue_text": "Use of assert",
                    "issue_severity": "LOW",
                    "filename": "tests/test_policy.py",
                    "line_number": 1,
                },
                {
                    "test_id": "B101",
                    "issue_text": "Use of assert",
                    "issue_severity": "LOW",
                    "filename": "src/codepilot/policy.py",
                    "line_number": 2,
                },
            ]
        }
    )

    findings = parse_bandit_json(payload, Path("backend"))

    assert [(finding.rule_id, finding.path, finding.start_line) for finding in findings] == [
        ("B101", "src/codepilot/policy.py", 2)
    ]


def test_ruff_parser_normalizes_rule_location_and_fingerprint() -> None:
    findings = parse_ruff_json(
        json.dumps(
            [
                {
                    "code": "F401",
                    "message": "unused import",
                    "filename": "src/app.py",
                    "location": {"row": 3, "column": 1},
                    "end_location": {"row": 3, "column": 8},
                }
            ]
        )
    )
    assert findings[0].rule_id == "F401"
    assert findings[0].path == "src/app.py"


def test_ruff_parser_strips_worker_root_from_absolute_paths() -> None:
    findings = parse_ruff_json(
        json.dumps(
            [
                {
                    "code": "F401",
                    "message": "unused import",
                    "filename": "/workspace/repository/src/app.py",
                    "location": {"row": 3, "column": 1},
                }
            ]
        ),
        Path("/workspace/repository"),
    )
    assert findings[0].path == "src/app.py"
    assert findings[0].start_line == 3
    assert (
        findings[0].fingerprint
        == parse_ruff_json(
            json.dumps(
                [
                    {
                        "code": "F401",
                        "message": "unused import",
                        "filename": "src/app.py",
                        "location": {"row": 3, "column": 1},
                        "end_location": {"row": 3, "column": 8},
                    }
                ]
            )
        )[0].fingerprint
    )


def test_bandit_parser_maps_security_severity() -> None:
    findings = parse_bandit_json(
        json.dumps(
            {
                "results": [
                    {
                        "test_id": "B101",
                        "issue_text": "Use of assert",
                        "issue_severity": "MEDIUM",
                        "filename": "src/app.py",
                        "line_number": 4,
                        "line_range": [4],
                    }
                ]
            }
        )
    )
    assert findings[0].severity == "warning"
    assert findings[0].category == "security"
    assert findings[0].rule_id == "B101"


def test_radon_parser_emits_complexity_metric_and_finding() -> None:
    findings, complexity = parse_radon_cc_json(
        json.dumps({"src/app.py": [{"name": "run", "complexity": 12, "lineno": 8, "endline": 20}]})
    )
    assert complexity == 12
    assert findings[0].rule_id == "RADON-CC"
    assert findings[0].start_line == 8


class FakeRunner:
    def __init__(self, outputs: dict[str, ToolResult]) -> None:
        self.outputs = outputs
        self.calls: list[tuple[str, ...]] = []

    async def run(
        self,
        executable: str,
        args: tuple[str, ...],
        cwd: Path,
        timeout_seconds: float,
    ) -> ToolResult:
        del cwd, timeout_seconds
        self.calls.append((executable, *args))
        output = self.outputs[executable]
        if args == ("--version",):
            return ToolResult(0, output.execution.version or "1.0", "", output.execution)
        if executable == "ruff":
            return ToolResult(0, "[]", "", output.execution)
        if executable == "bandit":
            return ToolResult(0, '{"results": []}', "", output.execution)
        return ToolResult(0, '{"src/app.py": []}', "", output.execution)


def test_tool_adapters_capture_version_and_missing_tool_state(tmp_path: Path) -> None:
    context = AnalyzerContext(tmp_path, "abc123")
    runner = FakeRunner(
        {
            "ruff": ToolResult(0, "ruff-json", "", ToolExecution("ruff", "0.9", 0.1, True)),
            "bandit": ToolResult(
                0, '{"results": []}', "", ToolExecution("bandit", "1.7", 0.1, True)
            ),
            "radon": ToolResult(
                0, '{"src/app.py": []}', "", ToolExecution("radon", "6.0", 0.1, True)
            ),
        }
    )
    ruff = asyncio.run(RuffAnalyzer(runner=runner).analyze(context))
    bandit = asyncio.run(BanditAnalyzer(runner=runner).analyze(context))
    radon = asyncio.run(RadonAnalyzer(runner=runner).analyze(context))
    assert ruff.execution is not None and ruff.execution.version == "0.9"
    assert bandit.execution is not None and bandit.execution.available
    assert radon.execution is not None and radon.execution.tool == "radon"
    assert runner.calls


def test_ruff_analyzer_passes_deterministic_source_roots_for_isolated_isort(tmp_path: Path) -> None:
    for root, package_name in _EXPECTED_RUFF_SOURCE_ROOTS:
        source = tmp_path / root
        source.mkdir(parents=True)
        package = source / package_name
        package.mkdir()
        (package / "__init__.py").write_text("value = 1\n", encoding="utf-8")
    runner = FakeRunner(
        {"ruff": ToolResult(0, "ruff-json", "", ToolExecution("ruff", "0.9", 0.1, True))}
    )

    asyncio.run(RuffAnalyzer(runner=runner).analyze(AnalyzerContext(tmp_path, "abc123")))

    ruff_scan = next(call for call in runner.calls if call[0] == "ruff" and "check" in call)
    assert "--isolated" in ruff_scan
    config_values = tuple(
        ruff_scan[index + 1] for index, value in enumerate(ruff_scan) if value == "--config"
    )
    assert config_values == (
        'src=["backend/src","packages/src"]',
        'lint.isort.known-first-party=["codepilot","widgets"]',
    )
