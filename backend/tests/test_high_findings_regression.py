from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
from radon.complexity import cc_visit  # type: ignore[import-untyped]

_MEDIUM_COMPLEXITY_THRESHOLD = 10
_AFFECTED_MODULES: Final[tuple[Path, ...]] = (
    Path("src/codepilot/services/analysis.py"),
    Path("src/codepilot/analyzers/risk_score.py"),
    Path("src/codepilot/domain/quality.py"),
    Path("src/codepilot/services/source_context.py"),
    Path("src/codepilot/analyzers/production.py"),
    Path("src/codepilot/services/repository_ingestion.py"),
    Path("src/codepilot/analyzers/git_history.py"),
    Path("src/codepilot/domain/insights.py"),
    Path("src/codepilot/services/llm_configuration.py"),
    Path("src/codepilot/analyzers/dependency_graph.py"),
    Path("src/codepilot/analyzers/multilanguage_adapters.py"),
    Path("src/codepilot/domain/analysis.py"),
    Path("src/codepilot/repositories/analysis.py"),
    Path("src/codepilot/llm/gateway.py"),
    Path("src/codepilot/api/v1/analyses.py"),
    Path("tests/test_analysis_api.py"),
    Path("tests/test_risk_score.py"),
    Path("tests/test_logging.py"),
    Path("tests/test_errors.py"),
)


@pytest.mark.parametrize("relative_path", _AFFECTED_MODULES)
def test_affected_modules_have_no_medium_or_high_cyclomatic_complexity(
    relative_path: Path,
) -> None:
    source_path = Path(__file__).parents[1] / relative_path
    violations = tuple(
        f"{block.name}={block.complexity}"
        for block in cc_visit(source_path.read_text(encoding="utf-8"))
        if block.complexity >= _MEDIUM_COMPLEXITY_THRESHOLD
    )

    assert violations == ()
