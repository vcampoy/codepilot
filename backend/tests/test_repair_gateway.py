import asyncio
import json
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet

from codepilot.domain.fixes import FixTargetType
from codepilot.domain.llm_config import LlmConfiguration
from codepilot.services.repair import RepairExecutionError, RepairRequest
from codepilot.services.repair_gateway import LiteLlmRepairGateway

_KEY = Fernet.generate_key().decode()
_PATCH = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-a
+b
"""


class Repository:
    async def get_llm_configuration(self, _workspace_id: str) -> LlmConfiguration:
        return LlmConfiguration(
            "default",
            True,
            "openai",
            "gpt-test",
            Fernet(_KEY.encode()).encrypt(b"api-key").decode(),
            datetime.now(UTC),
        )


def test_repair_gateway_validates_structured_provider_output() -> None:
    async def completion(**_kwargs: object) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"patch": _PATCH, "title": "Fix", "description": "Reason"}
                        )
                    }
                }
            ]
        }

    request = RepairRequest(FixTargetType.FINDING, ("finding-1",), (), "Use tests")
    gateway = LiteLlmRepairGateway(Repository(), _KEY, completion=completion)
    result = asyncio.run(gateway.generate_repair(request))

    assert result.patch == _PATCH
    assert result.title == "Fix"


@pytest.mark.parametrize(
    ("provider_error", "expected"),
    [
        (TimeoutError(), "Repair provider timed out."),
        (ConnectionError("connection refused"), "Repair provider is unavailable."),
        (PermissionError("401 unauthorized"), "Repair provider authentication failed."),
    ],
)
def test_repair_gateway_normalizes_provider_failures(
    provider_error: Exception, expected: str
) -> None:
    async def completion(**_kwargs: object) -> dict[str, object]:
        raise provider_error

    request = RepairRequest(FixTargetType.FINDING, ("finding-1",), (), "Use tests")
    gateway = LiteLlmRepairGateway(Repository(), _KEY, completion=completion)

    with pytest.raises(RepairExecutionError, match=expected):
        asyncio.run(gateway.generate_repair(request))


def test_repair_gateway_normalizes_sdk_timeout_error() -> None:
    class APITimeoutError(RuntimeError):
        pass

    async def completion(**_kwargs: object) -> dict[str, object]:
        raise APITimeoutError("request timed out")

    request = RepairRequest(FixTargetType.FINDING, ("finding-1",), (), "Use tests")
    gateway = LiteLlmRepairGateway(Repository(), _KEY, completion=completion)

    with pytest.raises(RepairExecutionError, match="Repair provider timed out"):
        asyncio.run(gateway.generate_repair(request))


def test_repair_gateway_normalizes_rate_limit_without_exposing_provider_details() -> None:
    class RateLimitError(RuntimeError):
        status_code = 429

    async def completion(**_kwargs: object) -> dict[str, object]:
        raise RateLimitError("api_key=super-secret quota exhausted")

    request = RepairRequest(FixTargetType.FINDING, ("finding-1",), (), "Use tests")
    gateway = LiteLlmRepairGateway(Repository(), _KEY, completion=completion)

    with pytest.raises(RepairExecutionError) as raised:
        asyncio.run(gateway.generate_repair(request))

    assert str(raised.value) == "Repair provider quota or rate limit exceeded."
    assert "super-secret" not in str(raised.value)


def test_repair_gateway_keeps_malformed_output_distinct_from_provider_failure() -> None:
    async def completion(**_kwargs: object) -> dict[str, object]:
        return {"choices": [{"message": {"content": "not json"}}]}

    request = RepairRequest(FixTargetType.FINDING, ("finding-1",), (), "Use tests")
    gateway = LiteLlmRepairGateway(Repository(), _KEY, completion=completion)

    with pytest.raises(RepairExecutionError, match="Repair model returned an invalid response"):
        asyncio.run(gateway.generate_repair(request))
