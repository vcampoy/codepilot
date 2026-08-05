"""Bounded structural dependency graphs for supported source languages."""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from codepilot.analyzers.framework import NormalizedFinding


@dataclass(frozen=True, slots=True)
class GraphLimits:
    max_nodes: int = 10_000
    max_edges: int = 50_000
    max_file_bytes: int = 1_000_000
    max_fan_out: int = 25

    def __post_init__(self) -> None:
        if min(self.max_nodes, self.max_edges, self.max_file_bytes, self.max_fan_out) <= 0:
            raise ValueError("graph limits must be positive")


@dataclass(frozen=True, slots=True)
class GraphNode:
    identifier: str
    node_type: str = "file"


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source: str
    target: str
    edge_type: str
    analyzer: str


@dataclass(frozen=True, slots=True)
class GraphPage:
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    total_nodes: int
    total_edges: int


@dataclass(frozen=True, slots=True)
class DependencyGraph:
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    cycles: tuple[tuple[str, ...], ...]
    in_degree: dict[str, int]
    out_degree: dict[str, int]
    isolated_nodes: tuple[str, ...]
    findings: tuple[NormalizedFinding, ...]

    def page(self, offset: int = 0, limit: int = 100) -> GraphPage:
        if offset < 0 or limit <= 0:
            raise ValueError("offset must be non-negative and limit must be positive")
        bounded = min(limit, 1_000)
        return GraphPage(
            nodes=self.nodes[offset : offset + bounded],
            edges=self.edges[offset : offset + bounded],
            total_nodes=len(self.nodes),
            total_edges=len(self.edges),
        )


class PythonImportExtractor:
    def extract(self, path: Path, root: Path) -> tuple[str, ...]:
        if path.suffix != ".py" or path.stat().st_size > 1_000_000:
            return ()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError):
            return ()
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        return tuple(
            sorted(target for module in modules if (target := _python_target(module, root)))
        )


class TypeScriptImportExtractor:
    _pattern = re.compile(r"(?:from\s+|import\s*\(\s*|require\(\s*)['\"]([^'\"]+)['\"]")

    def extract(self, path: Path, root: Path) -> tuple[str, ...]:
        if path.suffix.lower() not in {".js", ".jsx", ".ts", ".tsx"}:
            return ()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return ()
        targets: set[str] = set()
        for module in self._pattern.findall(text):
            if module.startswith("."):
                target = _javascript_target(path.parent / module, root)
                if target:
                    targets.add(target)
        return tuple(sorted(targets))


class CSharpReferenceExtractor:
    _project = re.compile(r"<ProjectReference[^>]+Include=['\"]([^'\"]+)")
    _namespace = re.compile(r"\busing\s+([A-Za-z_][\w.]*)\s*;")

    def extract(self, path: Path, root: Path) -> tuple[str, ...]:
        if path.suffix.lower() not in {".cs", ".csproj"}:
            return ()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return ()
        if path.suffix.lower() == ".csproj":
            return tuple(
                sorted(
                    target.relative_to(root).as_posix()
                    for value in self._project.findall(text)
                    if (target := (path.parent / value).resolve()).exists()
                )
            )
        return tuple(sorted(self._namespace.findall(text)))


class DependencyGraphBuilder:
    def __init__(self, limits: GraphLimits | None = None) -> None:
        self._limits = limits or GraphLimits()
        self._python = PythonImportExtractor()
        self._typescript = TypeScriptImportExtractor()
        self._csharp = CSharpReferenceExtractor()

    def build(self, root: Path) -> DependencyGraph:
        paths = sorted(
            path
            for path in root.rglob("*")
            if path.is_file() and path.stat().st_size <= self._limits.max_file_bytes
        )[: self._limits.max_nodes]
        identifiers = {path.relative_to(root).as_posix() for path in paths}
        nodes = tuple(GraphNode(identifier) for identifier in sorted(identifiers))
        edges: set[GraphEdge] = set()
        for path in paths:
            source = path.relative_to(root).as_posix()
            extractor = (
                self._python
                if path.suffix == ".py"
                else self._typescript
                if path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx"}
                else self._csharp
            )
            for target in extractor.extract(path, root):
                if target in identifiers and len(edges) < self._limits.max_edges:
                    analyzer = type(extractor).__name__
                    edges.add(GraphEdge(source, target, "imports", analyzer))
        ordered_edges = tuple(
            sorted(edges, key=lambda edge: (edge.source, edge.target, edge.analyzer))
        )
        out_degree: defaultdict[str, int] = defaultdict(int)
        in_degree: defaultdict[str, int] = defaultdict(int)
        for edge in ordered_edges:
            out_degree[edge.source] += 1
            in_degree[edge.target] += 1
        cycles = _strongly_connected_components(identifiers, ordered_edges)
        findings = _architecture_findings(
            cycles, out_degree, ordered_edges, self._limits.max_fan_out
        )
        isolated = tuple(
            sorted(node for node in identifiers if not in_degree[node] and not out_degree[node])
        )
        return DependencyGraph(
            nodes=nodes,
            edges=ordered_edges,
            cycles=cycles,
            in_degree=dict(in_degree),
            out_degree=dict(out_degree),
            isolated_nodes=isolated,
            findings=findings,
        )


def _python_target(module: str, root: Path) -> str | None:
    candidate = root / (module.replace(".", "/") + ".py")
    if candidate.exists():
        return candidate.relative_to(root).as_posix()
    package = root / module.replace(".", "/") / "__init__.py"
    return package.relative_to(root).as_posix() if package.exists() else None


def _javascript_target(candidate: Path, root: Path) -> str | None:
    for suffix in ("", ".ts", ".tsx", ".js", ".jsx"):
        path = Path(f"{candidate}{suffix}")
        if path.exists():
            return path.relative_to(root).as_posix()
    index = candidate / "index.ts"
    return index.relative_to(root).as_posix() if index.exists() else None


def _strongly_connected_components(
    identifiers: set[str], edges: tuple[GraphEdge, ...]
) -> tuple[tuple[str, ...], ...]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        adjacency[edge.source].append(edge.target)
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in adjacency[node]:
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] == indices[node]:
            component: list[str] = []
            while True:
                target = stack.pop()
                on_stack.remove(target)
                component.append(target)
                if target == node:
                    break
            if len(component) > 1 or any(
                edge.source == node and edge.target == node for edge in edges
            ):
                components.append(tuple(sorted(component)))

    for node in sorted(identifiers):
        if node not in indices:
            visit(node)
    return tuple(sorted(components))


def _architecture_findings(
    cycles: tuple[tuple[str, ...], ...],
    out_degree: dict[str, int],
    edges: tuple[GraphEdge, ...],
    max_fan_out: int,
) -> tuple[NormalizedFinding, ...]:
    findings: list[NormalizedFinding] = []
    for component in cycles:
        evidence = "; ".join(
            f"{edge.source}->{edge.target}"
            for edge in edges
            if edge.source in component and edge.target in component
        )
        findings.append(
            NormalizedFinding(
                analyzer="architecture.graph",
                rule_id="ARCH001",
                severity="warning",
                category="architecture",
                title="Dependency cycle",
                description="A strongly connected dependency component was detected.",
                path=component[0],
                start_line=1,
                end_line=1,
                evidence=evidence,
            )
        )
    for source, degree in sorted(out_degree.items()):
        if degree > max_fan_out:
            findings.append(
                NormalizedFinding(
                    analyzer="architecture.graph",
                    rule_id="ARCH002",
                    severity="warning",
                    category="architecture",
                    title="Excessive dependency fan-out",
                    description="The module imports more dependencies than the configured limit.",
                    path=source,
                    start_line=1,
                    end_line=1,
                    evidence=f"out_degree={degree}",
                )
            )
    return tuple(findings)
