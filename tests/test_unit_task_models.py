"""Unit tests for task models."""

import datetime

import pytest
from pydantic import ValidationError

from task_api.tasks.models import TITLE_MAX, TaskCreate


def _locs(exc: ValidationError) -> list[str]:
    return [str(e["loc"][-1]) for e in exc.errors()]


@pytest.mark.parametrize("title", ["Buy milk", "  Buy milk  ", "a" * TITLE_MAX, "é" * TITLE_MAX])
def test_title_accepted_untrimmed(title: str) -> None:
    assert TaskCreate.model_validate({"title": title}).title == title


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"title": ""},
        {"title": "   "},
        {"title": "\t\n"},
        {"title": " "},
        {"title": 42},
        {"title": None},
        {"title": ["x"]},
        {"title": "a" * (TITLE_MAX + 1)},
        {"title": "é" * (TITLE_MAX + 1)},
    ],
)
def test_title_rejected(body: dict) -> None:
    with pytest.raises(ValidationError) as ei:
        TaskCreate.model_validate(body)
    assert _locs(ei.value) == ["title"]
    ei.value.errors(include_url=False)
    ei.value.json()


@pytest.mark.parametrize(
    "due", [None, "2026-12-31", "2020-01-15", datetime.date.today().isoformat()]
)
def test_due_date_accepted(due: str | None) -> None:
    assert TaskCreate.model_validate({"title": "t", "due_date": due}).due_date == due


def test_due_date_absent_is_none() -> None:
    assert TaskCreate.model_validate({"title": "t"}).due_date is None


@pytest.mark.parametrize(
    "due",
    [
        "",
        "31.12.2026",
        "2026-02-30",
        "tomorrow",
        "2026-1-5",
        "2026-12-31T10:00:00",
        42,
        "２０２６-12-31",
    ],
)
def test_due_date_rejected(due: object) -> None:
    with pytest.raises(ValidationError) as ei:
        TaskCreate.model_validate({"title": "t", "due_date": due})
    assert _locs(ei.value) == ["due_date"]
    ei.value.json()


def test_both_invalid_report_both_fields() -> None:
    with pytest.raises(ValidationError) as ei:
        TaskCreate.model_validate({"title": "", "due_date": "tomorrow"})
    assert sorted(_locs(ei.value)) == ["due_date", "title"]


def test_unknown_field_ignored() -> None:
    m = TaskCreate.model_validate({"title": "t", "colour": "red"})
    assert "colour" not in m.model_dump()
