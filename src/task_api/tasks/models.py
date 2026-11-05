"""Request and response models for tasks."""

import datetime
import re

from pydantic import BaseModel, Field, StrictStr, field_validator
from pydantic_core import PydanticCustomError

TITLE_MAX = 200

_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class TaskCreate(BaseModel):
    """Body of POST /tasks."""

    title: StrictStr = Field(max_length=TITLE_MAX)
    due_date: StrictStr | None = None

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise PydanticCustomError("title_blank", "title must not be empty or only whitespace")
        return v

    @field_validator("due_date")
    @classmethod
    def _due_date_valid(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            if not _DATE_RE.fullmatch(v):
                raise ValueError(v)
            datetime.date.fromisoformat(v)
        except ValueError:
            raise PydanticCustomError(
                "due_date_invalid", "due_date must be a valid date in YYYY-MM-DD format"
            ) from None
        return v


class Task(BaseModel):
    """A stored task as returned by the API."""

    id: str
    title: str
    due_date: str | None
