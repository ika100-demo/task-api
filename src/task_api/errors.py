"""Exception handlers."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from .tasks.store import TaskStoreUnavailable

logger = structlog.get_logger()


class ErrorMessage(BaseModel):
    detail: str


async def task_store_unavailable_handler(request: Request, exc: TaskStoreUnavailable) -> Response:
    """Map a store failure to 503 without leaking details."""
    logger.warning("task_store_unavailable", error=type(exc.__cause__).__name__)
    return JSONResponse(status_code=503, content={"detail": "The task store is unavailable."})


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> Response:
    """Report invalid JSON with loc ["body"] instead of a character offset."""
    errors: list[Any] = []
    for err in exc.errors():
        if err.get("type") == "json_invalid":
            err = {**err, "loc": ("body",)}
        errors.append(err)
    new_exc = RequestValidationError(errors, body=exc.body)
    return await request_validation_exception_handler(request, new_exc)
