"""Representative deterministic medium-repository performance guard."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

from codepilot.analyzers.dependency_graph import DependencyGraphBuilder, GraphLimits


def test_dependency_graph_handles_medium_repository_within_mvp_budget(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    for index in range(250):
        import_line = f"from package.module_{index - 1} import value\n" if index else ""
        (package / f"module_{index}.py").write_text(
            f"{import_line}value = {index}\n", encoding="utf-8"
        )

    started = perf_counter()
    graph = DependencyGraphBuilder(
        GraphLimits(max_nodes=500, max_edges=1_000, max_file_bytes=100_000, max_fan_out=25)
    ).build(tmp_path)
    elapsed = perf_counter() - started

    assert len(graph.nodes) == 250
    assert len(graph.edges) == 249
    assert elapsed < 5
