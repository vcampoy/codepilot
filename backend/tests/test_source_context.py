from pathlib import Path

from codepilot.domain.analysis import AnalysisFinding
from codepilot.services.source_context import capture_source_context


def test_capture_source_context_includes_five_lines_and_highlight_range(tmp_path: Path) -> None:
    source = tmp_path / "src" / "main.py"
    source.parent.mkdir()
    source.write_text("\n".join(f"line {index}" for index in range(1, 15)), encoding="utf-8")
    finding = AnalysisFinding("src/main.py", "R1", "high", "bad", 7, 8)

    context = capture_source_context(tmp_path, finding)

    assert context is not None
    assert context.start_line == 2
    assert context.end_line == 13
    assert tuple(line.number for line in context.lines) == tuple(range(2, 14))
    assert tuple(line.highlighted for line in context.lines) == (
        (False,) * 5 + (True, True) + (False,) * 5
    )


def test_capture_source_context_skips_unsafe_binary_sensitive_and_oversized_files(
    tmp_path: Path,
) -> None:
    binary = tmp_path / "binary.py"
    binary.write_bytes(b"ok\x00bad")
    sensitive = tmp_path / ".env"
    sensitive.write_text("TOKEN=secret", encoding="utf-8")
    credentials = tmp_path / ".npmrc"
    credentials.write_text("//registry/:_authToken=secret", encoding="utf-8")
    outside = AnalysisFinding("../outside.py", "R1", "high", "bad", 1, 1)
    assert capture_source_context(tmp_path, outside) is None
    assert capture_source_context(
        tmp_path, AnalysisFinding("binary.py", "R1", "high", "bad", 1, 1)
    ) is None
    assert capture_source_context(
        tmp_path, AnalysisFinding(".env", "R1", "high", "bad", 1, 1)
    ) is None
    assert capture_source_context(
        tmp_path, AnalysisFinding(".npmrc", "R1", "high", "bad", 1, 1)
    ) is None


def test_capture_source_context_rejects_malformed_finding_ranges(tmp_path: Path) -> None:
    source = tmp_path / "main.py"
    source.write_text("one\ntwo\n", encoding="utf-8")
    malformed = (
        AnalysisFinding("main.py", "R1", "high", "bad", 0, 1),
        AnalysisFinding("main.py", "R1", "high", "bad", 2, 1),
        AnalysisFinding("main.py", "R1", "high", "bad", 3, 3),
    )
    assert all(capture_source_context(tmp_path, finding) is None for finding in malformed)


def test_capture_source_context_clamps_end_line_to_file_length(tmp_path: Path) -> None:
    source = tmp_path / "main.py"
    source.write_text("one\ntwo\n", encoding="utf-8")
    finding = AnalysisFinding("main.py", "R1", "high", "bad", 2, 99)

    context = capture_source_context(tmp_path, finding)

    assert context is not None
    assert context.end_line == 2
