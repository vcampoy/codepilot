from __future__ import annotations

from pathlib import Path

from codepilot.analyzers.dependency_graph import (
    DependencyGraphBuilder,
    GraphLimits,
    PythonImportExtractor,
)


def test_python_fixture_builds_edges_cycles_and_architecture_findings(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("import b\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("from a import value\n", encoding="utf-8")
    graph = DependencyGraphBuilder(GraphLimits(max_nodes=20)).build(tmp_path)

    assert {(edge.source, edge.target) for edge in graph.edges} == {
        ("a.py", "b.py"),
        ("b.py", "a.py"),
    }
    assert {frozenset(component) for component in graph.cycles} == {frozenset({"a.py", "b.py"})}
    assert any(finding.rule_id == "ARCH001" for finding in graph.findings)
    assert all(finding.evidence for finding in graph.findings)


def test_typescript_imports_are_structural_and_graph_pages_are_bounded(tmp_path: Path) -> None:
    (tmp_path / "main.ts").write_text("import {x} from './lib';\n", encoding="utf-8")
    (tmp_path / "lib.ts").write_text("export const x = 1;\n", encoding="utf-8")
    graph = DependencyGraphBuilder(GraphLimits(max_nodes=20)).build(tmp_path)

    assert any(edge.source == "main.ts" and edge.target == "lib.ts" for edge in graph.edges)
    assert len(graph.page(offset=0, limit=1).nodes) == 1
    assert len(graph.page(offset=0, limit=10).edges) <= 10


def test_extractors_ignore_unsupported_or_oversized_inputs(tmp_path: Path) -> None:
    (tmp_path / "data.txt").write_text("import b\n", encoding="utf-8")
    assert PythonImportExtractor().extract(tmp_path / "data.txt", tmp_path) == ()
