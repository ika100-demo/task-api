"""POST /tasks and GET /tasks."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request

from ..errors import ErrorMessage
from .models import Task, TaskCreate
from .store import TaskRecord, TaskStore

router = APIRouter(tags=["tasks"])
logger = structlog.get_logger()

_UNAVAILABLE: dict[int | str, dict[str, Any]] = {
    503: {"model": ErrorMessage, "description": "The task store is unavailable"}
}


def get_task_store(request: Request) -> TaskStore:
    store: TaskStore = request.app.state.task_store
    return store


def _to_task(record: TaskRecord) -> Task:
    return Task(id=record.id, title=record.title, due_date=record.due_date)


@router.post("/tasks", status_code=201, response_model=Task, responses=_UNAVAILABLE)
def create_task(body: TaskCreate, store: TaskStore = Depends(get_task_store)) -> Task:  # noqa: B008
    """Create a task."""
    record = store.add(body.title, body.due_date)
    logger.info("task_created", task_id=record.id)
    return _to_task(record)


@router.get("/tasks", response_model=list[Task], responses=_UNAVAILABLE)
def list_tasks(store: TaskStore = Depends(get_task_store)) -> list[Task]:  # noqa: B008
    """List tasks in creation order."""
    return [_to_task(r) for r in store.list()]
