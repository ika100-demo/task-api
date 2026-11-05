"""Process-wide, thread-safe in-memory task storage."""

import threading
import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TaskRecord:
    id: str
    title: str
    due_date: str | None


class TaskStore:
    def __init__(self) -> None:
        self._tasks: list[TaskRecord] = []
        self._lock = threading.Lock()

    def add(self, title: str, due_date: str | None) -> TaskRecord:
        record = TaskRecord(id=str(uuid.uuid4()), title=title, due_date=due_date)
        with self._lock:
            self._tasks.append(record)
        return record

    def list(self) -> list[TaskRecord]:
        with self._lock:
            return list(self._tasks)
