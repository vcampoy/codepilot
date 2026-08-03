import json
import logging

from fastapi.testclient import TestClient

from codepilot.core.settings import Settings
from codepilot.main import create_app


def test_json_request_log_contains_safe_structured_fields(capsys) -> None:  # type: ignore[no-untyped-def]
    application = create_app(Settings(log_format="json"))
    with TestClient(application) as client:
        client.get("/health?secret=query-value", headers={"X-Correlation-ID": "log-test"})

    output = capsys.readouterr().out
    records = [json.loads(line) for line in output.splitlines() if line.strip()]
    request_record = next(
        record for record in records if record.get("event") == "request.completed"
    )
    assert request_record["correlation_id"] == "log-test"
    assert request_record["method"] == "GET"
    assert request_record["path"] == "/health"
    assert request_record["status"] == 200
    assert isinstance(request_record["duration_ms"], float)
    assert "query-value" not in output
    assert "secret=" not in output


def test_logging_configuration_sets_requested_level() -> None:
    create_app(Settings(log_level="WARNING"))

    assert logging.getLogger().level == logging.WARNING
