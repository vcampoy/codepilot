import json
import logging

import pytest
from fastapi.testclient import TestClient

from codepilot.core.settings import Settings
from codepilot.main import create_app


def _request_json_log(capsys: pytest.CaptureFixture[str]) -> str:
    application = create_app(Settings(log_format="json"))
    with TestClient(application) as client:
        client.get("/health?secret=query-value", headers={"X-Correlation-ID": "log-test"})

    return capsys.readouterr().out


def test_json_request_log_contains_safe_structured_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = _request_json_log(capsys)
    records = [json.loads(line) for line in output.splitlines() if line.strip()]
    request_record = next(
        record for record in records if record.get("event") == "request.completed"
    )
    assert (
        request_record["correlation_id"],
        request_record["method"],
        request_record["path"],
        request_record["status"],
        type(request_record["duration_ms"]),
    ) == ("log-test", "GET", "/health", 200, float)


def test_json_request_log_redacts_query_values(capsys: pytest.CaptureFixture[str]) -> None:
    output = _request_json_log(capsys)
    assert "query-value" not in output
    assert "secret=" not in output


def test_logging_configuration_sets_requested_level() -> None:
    create_app(Settings(log_level="WARNING"))

    assert logging.getLogger().level == logging.WARNING
