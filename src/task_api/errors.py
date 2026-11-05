"""Exception handlers."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> Response:
    """Report invalid JSON with loc ["body"] instead of a character offset."""
    errors: list[Any] = []
    for err in exc.errors():
        if err.get("type") == "json_invalid":
            err = {**err, "loc": ("body",)}
        errors.append(err)
    new_exc = RequestValidationError(errors, body=exc.body)
    return await request_validation_exception_handler(request, new_exc)
