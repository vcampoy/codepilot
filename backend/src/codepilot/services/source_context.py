"""Safe, bounded source snippets for persisted finding evidence."""

from __future__ import annotations

from pathlib import Path

from codepilot.domain.analysis import AnalysisFinding, SourceContext, SourceLine

_CONTEXT_LINES = 5
_MAX_FILE_BYTES = 1_048_576
_MAX_LINE_BYTES = 16_384
_MAX_FRAGMENT_BYTES = 64_000
_SENSITIVE_NAMES = frozenset(
    {".env", ".env.local", ".env.production", ".npmrc", ".pypirc", "id_rsa"}
)
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".secret")
_SENSITIVE_PREFIXES = ("credentials", "secrets")


def capture_source_context(repository_root: Path, finding: AnalysisFinding) -> SourceContext | None:
    """Capture a tiny source window while rejecting unsafe or sensitive paths.

    Only the bounded excerpt is persisted; the cloned worktree is never retained.
    """
    root = repository_root.resolve()
    path = _safe_finding_path(root, finding.path)
    if path is None or _is_sensitive_filename(path.name):
        return None
    lines = _read_source_lines(path)
    if lines is None:
        return None
    if not lines:
        return None
    if finding.start_line < 1 or finding.end_line < finding.start_line:
        return None
    if finding.start_line > len(lines):
        return None
    return _build_source_context(lines, finding)


def _safe_finding_path(root: Path, finding_path: str) -> Path | None:
    normalized = finding_path.replace("\\", "/")
    candidate = Path(normalized)
    path = (candidate if candidate.is_absolute() else root / candidate).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def _read_source_lines(path: Path) -> list[str] | None:
    try:
        if not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
            return None
        raw = path.read_bytes()
        if b"\x00" in raw:
            return None
        return raw.decode("utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None


def _build_source_context(lines: list[str], finding: AnalysisFinding) -> SourceContext | None:
    requested_start = max(1, finding.start_line - _CONTEXT_LINES)
    requested_end = min(len(lines), finding.end_line + _CONTEXT_LINES)
    selected: list[SourceLine] = []
    total_bytes = 0
    for number in range(requested_start, requested_end + 1):
        line = lines[number - 1]
        if len(line.encode("utf-8")) > _MAX_LINE_BYTES:
            return None
        encoded_size = len(line.encode("utf-8"))
        if total_bytes + encoded_size > _MAX_FRAGMENT_BYTES:
            return None
        selected.append(SourceLine(number, line, finding.start_line <= number <= finding.end_line))
        total_bytes += encoded_size
    return SourceContext(requested_start, requested_end, tuple(selected))


def _is_sensitive_filename(name: str) -> bool:
    lowered = name.casefold()
    if lowered in _SENSITIVE_NAMES or lowered.endswith(_SENSITIVE_SUFFIXES):
        return True
    if lowered.startswith(_SENSITIVE_PREFIXES):
        return True
    return "config" in lowered and any(
        marker in lowered for marker in ("secret", "token", "credential", "password")
    )


def enrich_findings_with_source_context(
    repository_root: Path, findings: tuple[AnalysisFinding, ...]
) -> tuple[AnalysisFinding, ...]:
    """Return findings with bounded snippets, preserving immutable input."""
    return tuple(
        AnalysisFinding(
            path=finding.path,
            rule_id=finding.rule_id,
            severity=finding.severity,
            message=finding.message,
            start_line=finding.start_line,
            end_line=finding.end_line,
            analyzer=finding.analyzer,
            category=finding.category,
            title=finding.title,
            evidence=finding.evidence,
            remediation=finding.remediation,
            source_context=capture_source_context(repository_root, finding),
        )
        for finding in findings
    )
