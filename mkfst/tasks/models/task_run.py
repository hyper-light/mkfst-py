from __future__ import annotations
import time
from typing import Any, Optional
import msgspec
from .run_status import RunStatus
from .task_type import TaskType


class TaskRun(msgspec.Struct):
    run_id: int
    task_name: str
    status: RunStatus
    error: Optional[str] = None
    trace: Optional[str] = None
    start: int | float = time.monotonic()
    end: Optional[int | float] = None
    elapsed: int | float = 0
    result: Optional[Any] = None
    task_type: TaskType = TaskType.CALLABLE

    def complete(self):
        return self.status in [
            RunStatus.COMPLETE,
            RunStatus.CANCELLED,
            RunStatus.FAILED,
        ]
