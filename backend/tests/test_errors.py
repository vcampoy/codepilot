from typing import Annotated

from fastapi import Body, HTTPException
from fastapi.testclient import TestClient

from codepilot.core.errors import ApplicationError
from codepilot.core.settings import Settings
from codepilot.main import create_app


def _client() -> TestClient:
    settings = Settings(cors_origins=["http://client.example"])
    application = create_app(settings)

    @application.get("/test/application-error")
    async def application_error() -> None:
        raise ApplicationError("example_error", "The example failed.", details={"field": "name"})

    @application.get("/test/unexpected-error")
    async def unexpected_error() -> None:
        raise RuntimeError("private exception secret")

    @application.get("/test/http-error")
    async def http_error() -> None:
        raise HTTPException(status_code=418, detail="secret detail must not be exposed")

    @application.post("/test/validation-error")
    async def validation_error(value: Annotated[int, Body(..., gt=0)]) -> dict[str, int]:
        return {"value": value}

    return TestClient(application, raise_server_exceptions=False)


def test_correlation_id_is_accepted_and_returned() -> None:
    with _client() as client:
        response = client.get("/health", headers={"X-Correlation-ID": "request-42"})

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "request-42"


def test_invalid_correlation_id_is_replaced() -> None:
    with _client() as client:
        response = client.get("/health", headers={"X-Correlation-ID": "bad value\nsecret"})

    correlation_id = response.headers["X-Correlation-ID"]
    assert correlation_id != "bad value\nsecret"
    assert len(correlation_id) == 36


def test_all_error_classes_have_stable_contract_and_correlation() -> None:
    with _client() as client:
        responses = [
            client.post("/test/validation-error", json={"value": "wrong"}),
            client.get("/test/application-error"),
            client.get("/missing"),
            client.get("/test/unexpected-error"),
            client.get("/test/http-error"),
        ]

    assert [response.status_code for response in responses] == [422, 400, 404, 500, 418]
    for response in responses:
        payload = response.json()
        assert set(payload) == {"error"}
        assert set(payload["error"]) >= {"code", "message", "correlation_id"}
        assert response.headers["X-Correlation-ID"] == payload["error"]["correlation_id"]
    assert responses[0].json()["error"]["details"][0]["location"] == ["body"]
    assert "wrong" not in responses[0].text
    assert "private exception secret" not in responses[3].text
    assert responses[3].json()["error"]["message"] == "An unexpected error occurred."
    assert "secret detail must not be exposed" not in responses[4].text
    assert responses[4].json()["error"]["message"] == "HTTP request failed."


def test_http_exception_messages_are_safe_and_status_specific() -> None:
    with _client() as client:
        not_found = client.get("/missing")
        method_not_allowed = client.post("/health")

    assert not_found.json()["error"]["message"] == "Resource not found."
    assert method_not_allowed.json()["error"]["message"] == "Method not allowed."


def test_cors_and_preflight_responses_have_correlation() -> None:
    with _client() as client:
        response = client.options(
            "/health",
            headers={"Origin": "http://client.example", "Access-Control-Request-Method": "GET"},
        )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://client.example"
    assert response.headers["X-Correlation-ID"]
