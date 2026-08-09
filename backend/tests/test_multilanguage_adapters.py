from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from codepilot.analyzers.framework import AnalyzerContext
from codepilot.analyzers.multilanguage_adapters import (
    EslintAnalyzer,
    SarifFileAnalyzer,
    SarifTooDeepError,
    SarifTooLargeError,
    _load_sarif_document,
    parse_eslint_json,
    parse_sarif_json,
)


def test_eslint_json_is_normalized() -> None:
    findings = parse_eslint_json(
        json.dumps(
            [
                {
                    "filePath": "src/app.ts",
                    "messages": [
                        {
                            "ruleId": "no-eval",
                            "severity": 2,
                            "message": "Do not use eval.",
                            "line": 4,
                            "endLine": 4,
                        }
                    ],
                }
            ]
        )
    )
    assert findings[0].analyzer == "javascript.eslint"
    assert findings[0].rule_id == "no-eval"
    assert findings[0].severity == "error"
    assert findings[0].path == "src/app.ts"


def test_eslint_paths_are_relative_to_repository_root() -> None:
    findings = parse_eslint_json(
        json.dumps(
            [
                {
                    "filePath": "/workspace/repository/src/app.ts",
                    "messages": [{"ruleId": "no-eval", "line": 2, "message": "Avoid eval."}],
                }
            ]
        ),
        Path("/workspace/repository"),
    )
    assert findings[0].path == "src/app.ts"


def test_sarif_roslyn_result_is_normalized_with_fingerprint() -> None:
    findings = parse_sarif_json(
        json.dumps(
            {
                "version": "2.1.0",
                "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
                "runs": [
                    {
                        "tool": {"driver": {"name": "Roslyn", "version": "4.8"}},
                        "results": [
                            {
                                "ruleId": "CA1000",
                                "level": "warning",
                                "message": {"text": "Avoid static members."},
                                "fingerprints": {"primaryLocationLineHash": "stable"},
                                "locations": [
                                    {
                                        "physicalLocation": {
                                            "artifactLocation": {"uri": "src/Type.cs"},
                                            "region": {"startLine": 8, "endLine": 9},
                                        }
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )
    )
    assert findings[0].analyzer == "Roslyn"
    assert findings[0].rule_id == "CA1000"
    assert findings[0].severity == "warning"
    assert findings[0].path == "src/Type.cs"
    assert findings[0].evidence == "stable"


def test_sarif_rejects_malformed_nested_and_oversized_documents() -> None:
    with pytest.raises(ValueError, match="2.1.0"):
        parse_sarif_json('{"version":"1.0.0","runs":[]}')
    with pytest.raises(SarifTooLargeError):
        parse_sarif_json('{"version":"2.1.0","runs":[]}', max_bytes=5)
    nested: object = "leaf"
    for _ in range(8):
        nested = [nested]
    with pytest.raises(SarifTooDeepError):
        parse_sarif_json(json.dumps(nested), max_depth=3)


def test_sarif_loader_rejects_non_object_documents_with_type_error() -> None:
    with pytest.raises(TypeError, match="SARIF document must be a JSON object"):
        _load_sarif_document("[]", max_bytes=100, max_depth=3)


def test_sarif_file_analyzer_and_eslint_metadata(tmp_path: Path) -> None:
    sarif_path = tmp_path / "results.sarif"
    sarif_path.write_text('{"version":"2.1.0","runs":[]}', encoding="utf-8")
    context = AnalyzerContext(tmp_path, "abc123")
    sarif_result = asyncio.run(SarifFileAnalyzer(sarif_path).analyze(context))
    assert sarif_result.execution is not None
    assert sarif_result.execution.tool == "sarif-import"
    assert EslintAnalyzer.metadata.supported_languages == frozenset({"javascript", "typescript"})


def test_sarif_parser_flattens_multiple_runs_and_applies_defaults() -> None:
    findings = parse_sarif_json(
        json.dumps(
            {
                "version": "2.1.0",
                "runs": [
                    {"tool": {"driver": {"name": "Tool-A"}}, "results": []},
                    {
                        "tool": {"driver": {}},
                        "results": [
                            {
                                "ruleId": "RULE-1",
                                "message": {"text": "Problem"},
                                "locations": [],
                            }
                        ],
                    },
                ],
            }
        )
    )

    assert len(findings) == 1
    assert findings[0].analyzer == "SARIF"
    assert findings[0].severity == "warning"
    assert findings[0].path == "<unknown>"
    assert findings[0].start_line == 1
