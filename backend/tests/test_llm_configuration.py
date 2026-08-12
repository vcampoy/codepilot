from __future__ import annotations

import asyncio
from typing import Any, cast

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr

from codepilot.core.settings import Settings
from codepilot.main import create_app
from codepilot.repositories.analysis import InMemoryAnalysisRepository
from codepilot.services.analysis import AnalysisService


class FakeDiscovery:
    async def discover(self, provider: str, api_key: str) -> list[str]:
        return ["gpt-test"]


def _client(
    repository: InMemoryAnalysisRepository, *, with_encryption_key: bool = True
) -> TestClient:
    service = AnalysisService(
        repository,
        cast(Any, object()),
        cast(Any, object()),
        cast(Any, object()),
    )
    settings = Settings(
        llm_config_encryption_key=(
            SecretStr(Fernet.generate_key().decode()) if with_encryption_key else None
        )
    )
    return TestClient(create_app(settings, analysis_service=service, llm_discovery=FakeDiscovery()))


def test_llm_configuration_never_returns_api_key_and_is_tenant_scoped() -> None:
    repository = InMemoryAnalysisRepository()
    with _client(repository) as client:
        saved = client.put(
            "/api/v1/settings/llm",
            json={
                "enabled": True,
                "provider": "OpenAI",
                "model": "gpt-test",
                "api_key": "sk-secret",
            },
            headers={"X-Workspace-ID": "team-a"},
        )
        hidden = client.get("/api/v1/settings/llm", headers={"X-Workspace-ID": "team-b"})
    assert saved.status_code == 200
    assert saved.json() == {
        "enabled": True,
        "provider": "openai",
        "model": "gpt-test",
        "api_key_configured": True,
        "available_models": ["gpt-test"],
        "reasoning_effort": None,
        "reasoning_efforts_by_model": {"gpt-test": []},
    }
    assert "sk-secret" not in saved.text
    assert hidden.json()["api_key_configured"] is False
    stored = asyncio.run(repository.get_llm_configuration("team-a"))
    assert stored is not None
    assert stored.encrypted_api_key != "sk-secret"


def test_enabling_without_a_key_is_rejected() -> None:
    with _client(InMemoryAnalysisRepository()) as client:
        response = client.put(
            "/api/v1/settings/llm",
            json={"enabled": True, "provider": "openai", "model": "gpt-test"},
        )
    assert response.status_code == 400
    assert "API key" in str(response.json())


def test_saving_api_key_without_encryption_key_is_rejected() -> None:
    with _client(InMemoryAnalysisRepository(), with_encryption_key=False) as client:
        response = client.put(
            "/api/v1/settings/llm",
            json={
                "enabled": True,
                "provider": "openai",
                "model": "gpt-test",
                "api_key": "sk-secret",
            },
        )

    assert response.status_code == 503
    assert "LLM_CONFIG_ENCRYPTION_KEY" in response.text
    assert "sk-secret" not in response.text
