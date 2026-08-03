"""Public application errors and stable API error responses."""

from collections.abc import Mapping
from json import dumps
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApplicationError(Exception):
    """An expected error whose fields are safe to expose to API clients."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: Mapping[str, Any] | list[Any] | None = None,
    ) -> None:
        super().__init__()
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def error_response(
    request: Request,
    code: str,
    message: str,
    *,
    status_code: int,
    details: Mapping[str, Any] | list[Any] | None = None,
) -> JSONResponse:
    """Build the stable public error envelope."""
    bounded_details = details
    if details is not None and len(dumps(details, default=str)) > 4096:
        bounded_details = {"message": "Additional error details were omitted."}
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "correlation_id": request.state.correlation_id,
                **({"details": bounded_details} if bounded_details is not None else {}),
            }
        },
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details = [
        {
            "location": [str(item) for item in error.get("loc", ())],
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors()
    ]
    return error_response(
        request,
        "request_validation_error",
        "Request validation failed.",
        status_code=422,
        details=details,
    )


async def application_exception_handler(request: Request, exc: ApplicationError) -> JSONResponse:
    return error_response(
        request, exc.code, exc.message, status_code=exc.status_code, details=exc.details
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    messages = {404: "Resource not found.", 405: "Method not allowed."}
    return error_response(
        request,
        f"http_error_{exc.status_code}",
        messages.get(exc.status_code, "HTTP request failed."),
        status_code=exc.status_code,
    )


async def unexpected_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return error_response(
        request, "internal_server_error", "An unexpected error occurred.", status_code=500
    )
