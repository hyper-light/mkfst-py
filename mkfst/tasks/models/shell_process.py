from __future__ import annotations
import time
import msgspec
from typing import Literal, Any, Dict, Tuple
from .run_status import RunStatus
from .task_type import TaskType


CommandType = Literal["shell", "subprocess"]


class ShellProcess(msgspec.Struct):
    run_id: int
    task_name: str
    process_id: int
    command: str
    status: RunStatus
    args: Tuple[str, ...] | None = None
    return_code: int | None = None
    env: Dict[str, Any] | None = None
    working_directory: str | None = None
    command_type: CommandType = "subprocess"
    error: str | None = None
    trace: str | None = None
    start: int | float = time.monotonic()
    end: int | float | None = None
    elapsed: int | float = 0
    result: str | None = None
    task_type: TaskType = TaskType.SHELL

    def complete(self):
        return self.status in [
            RunStatus.COMPLETE,
            RunStatus.CANCELLED,
            RunStatus.FAILED,
        ]
