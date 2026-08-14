import asyncio

import pytest

from codepilot.domain.fixes import FixTargetType
from codepilot.services.repair import (
    NoopSandboxVerifier,
    RepairExecutionError,
    RepairExecutor,
    RepairRequest,
    RepairResponse,
    validate_unified_patch,
)


def test_validate_unified_patch_accepts_safe_source_paths():
    patch = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-return 1
+return 2
"""

    assert validate_unified_patch(patch) == ("src/app.py",)


@pytest.mark.parametrize(
    "patch",
    [
        "diff --git a/../secrets.txt b/../secrets.txt\n",
        "diff --git a/dist/app.js b/dist/app.js\n",
        "diff --git a/config.py b/config.py\napi_key = 'secret'\n",
    ],
)
def test_validate_unified_patch_rejects_unsafe_content(patch: str):
    with pytest.raises(ValueError):
        validate_unified_patch(patch)


def test_noop_sandbox_still_validates_patch():
    patch = "diff --git a/src/app.py b/src/app.py\n"

    result = asyncio.run(
        NoopSandboxVerifier().verify("https://github.com/acme/repo", "a" * 40, patch)
    )
    assert result == ()


def test_repair_request_keeps_target_type_and_rules():
    request = RepairRequest(FixTargetType.HOTSPOT, ("src/app.py",), (), "Use tests")

    assert request.target_type is FixTargetType.HOTSPOT
    assert request.rules == "Use tests"


def test_repair_executor_requires_verified_tests_before_publishing():
    class Gateway:
        async def generate_repair(self, _request):
            return RepairResponse("diff --git a/src/app.py b/src/app.py\n", "Fix", "Why")

    class Sandbox:
        async def verify(self, _url, _sha, _patch):
            return ()

    class Publisher:
        async def publish(self, *_args):
            raise AssertionError("publisher must not run")

    request = RepairRequest(FixTargetType.FINDING, ("id",), (), "rules")
    with pytest.raises(RepairExecutionError, match="did not run"):
        asyncio.run(
            RepairExecutor(Gateway(), Sandbox(), Publisher()).execute(
                request,
                repository_url="https://github.com/acme/repo",
                commit_sha="a" * 40,
                branch_name="fix-finding-job",
            )
        )
