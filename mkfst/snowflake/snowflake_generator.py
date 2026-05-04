"""Twitter-style 64-bit snowflake ID generator.

Layout (high → low bits):

* timestamp   — 41 bits, milliseconds since the configured epoch
* instance    — 10 bits, machine/process identity (caller must keep unique)
* sequence    — 12 bits, per-millisecond monotonic counter (4096 IDs/ms cap)

The original implementation had three correctness defects:

* Instance bits were not masked, so high-bit values bled into the timestamp.
* Sequence overflow returned ``None`` rather than waiting for the next ms,
  which forced callers to handle ``None`` keys and silently dropped IDs.
* Clock-step-backwards returned ``None`` rather than blocking until wall-clock
  caught up, which under any NTP correction crashed callers using the result
  as a dict key or string token.

The new implementation spin-waits past sequence overflow (~1µs) and clock
regressions (~1ms), preserving the contract that ``generate()`` always returns
a unique 64-bit integer.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from .constants import MAX_INSTANCE, MAX_SEQ
from .snowflake import Snowflake

_INSTANCE_SHIFT = 12
_TIMESTAMP_SHIFT = 22


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _wait_for_next_ms(after: int) -> int:
    """Block until the wall clock advances strictly past ``after`` ms."""
    while True:
        now = _now_ms()
        if now > after:
            return now
        # Sub-millisecond sleep yields to the loop without burning CPU.
        time.sleep(0.0005)


class SnowflakeGenerator:
    __slots__ = ("_lock", "_ts", "_seq", "_instance_bits", "_epoch")

    def __init__(
        self,
        instance: int,
        *,
        seq: int = 0,
        timestamp: Optional[int] = None,
        epoch: int = 0,
    ) -> None:
        if instance < 0:
            raise ValueError("instance must be non-negative")
        if seq < 0 or seq > MAX_SEQ:
            raise ValueError(f"seq must be in [0, {MAX_SEQ}]")

        # Mask the instance to the legal width so a caller-supplied identifier
        # cannot bleed into the timestamp region.
        self._instance_bits = (instance & MAX_INSTANCE) << _INSTANCE_SHIFT
        self._seq = seq
        self._epoch = epoch
        self._ts = timestamp if timestamp is not None else _now_ms()
        self._lock = threading.Lock()

    @classmethod
    def from_snowflake(cls, sf: Snowflake) -> "SnowflakeGenerator":
        return cls(sf.instance, seq=sf.seq, timestamp=sf.timestamp, epoch=sf.epoch)

    def __iter__(self) -> "SnowflakeGenerator":
        return self

    def __next__(self) -> int:
        return self.generate()

    def generate(self) -> int:
        """Produce the next ID. Always returns a fresh 64-bit integer."""
        with self._lock:
            now = _now_ms()

            if now < self._ts:
                # Clock stepped backward (NTP correction, suspended VM, etc).
                # Block on the lock until wall-clock catches up rather than
                # silently corrupting downstream identifiers.
                now = _wait_for_next_ms(self._ts - 1)

            if now == self._ts:
                self._seq += 1
                if self._seq > MAX_SEQ:
                    now = _wait_for_next_ms(self._ts)
                    self._ts = now
                    self._seq = 0
            else:
                self._ts = now
                self._seq = 0

            ts_part = (self._ts - self._epoch) & 0x1FFFFFFFFFF  # 41 bits
            return (ts_part << _TIMESTAMP_SHIFT) | self._instance_bits | self._seq
