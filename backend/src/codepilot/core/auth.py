"""Minimal API-key and workspace authentication for the public MVP."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass

from fastapi import Request

from codepilot.core.errors import ApplicationError

_WORKSPACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True, slots=True)
class RequestIdentity:
    """Authenticated tenant context used by all tenant-owned endpoints."""

    workspace_id: str
    subject: str


def authenticate(request: Request) -> RequestIdentity:
    """Authenticate the configured API key and normalize the workspace header."""
    settings = request.app.state.settings
    configured_key = settings.auth_api_key_value()
    supplied_key = request.headers.get("X-API-Key")
    if settings.auth_required and (
        not configured_key
        or not supplied_key
        or not secrets.compare_digest(supplied_key, configured_key)
    ):
        raise ApplicationError(
            "authentication_required", "Authentication is required.", status_code=401
        )
    workspace_id = request.headers.get("X-Workspace-ID", "local")
    if not _WORKSPACE_PATTERN.fullmatch(workspace_id):
        raise ApplicationError("invalid_workspace", "Workspace ID is invalid.", status_code=400)
    return RequestIdentity(workspace_id=workspace_id, subject="api-key")
