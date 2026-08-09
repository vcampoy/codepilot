from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
from radon.complexity import cc_visit  # type: ignore[import-untyped]

_HIGH_COMPLEXITY_THRESHOLD = 15
_AFFECTED_MODULES: Final[tuple[Path, ...]] = (
    Path("src/codepilot/services/repository_ingestion.py"),
    Path("src/codepilot/analyzers/dependency_graph.py"),
    Path("src/codepilot/analyzers/multilanguage_adapters.py"),
    Path("src/codepilot/core/settings.py"),
    Path("src/codepilot/github/diff_analysis.py"),
)


@pytest.mark.parametrize("relative_path", _AFFECTED_MODULES)
def test_affected_modules_have_no_high_cyclomatic_complexity(
    relative_path: Path,
) -> None:
    source_path = Path(__file__).parents[1] / relative_path
    violations = tuple(
        f"{block.name}={block.complexity}"
        for block in cc_visit(source_path.read_text(encoding="utf-8"))
        if block.complexity >= _HIGH_COMPLEXITY_THRESHOLD
    )

    assert violations == ()
