import asyncio
import json
from datetime import UTC, datetime

from cryptography.fernet import Fernet

from codepilot.domain.fixes import FixTargetType
from codepilot.domain.llm_config import LlmConfiguration
from codepilot.services.repair import RepairRequest
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
