from fastapi.testclient import TestClient

from codepilot.main import create_app


def test_health_returns_deterministic_status() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_versioned_api_discovery() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/")

    assert response.status_code == 200
    assert response.json() == {"name": "CodePilot API", "version": "v1"}


def test_application_factory_returns_isolated_instances() -> None:
    first_app = create_app()
    second_app = create_app()

    first_app.state.test_marker = True

    assert first_app is not second_app
    assert not hasattr(second_app.state, "test_marker")
