from __future__ import annotations
import time
from typing import Any, Optional

import orjson
import msgspec
from .run_status import RunStatus


class TaskRun(msgspec.Struct, kw_only=True):
    run_id: int
    status: RunStatus
    error: Optional[str] = None
    trace: Optional[str] = None
    start: int | float = time.monotonic()
    end: Optional[int | float] = None
    elapsed: int | float = 0
    result: Optional[Any] = None

    def to_json(self):
        return orjson.dumps(
            {
                "run_id": self.run_id,
                "status": self.status.value,
                "error": self.error,
                "start": self.start,
                "end": self.end,
                "elapsed": self.elapsed,
            }
        )

    def to_data(self):
        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "error": self.error,
            "start": self.start,
            "end": self.end,
            "elapsed": self.elapsed,
        }
