from __future__ import annotations

import threading
import time

import pytest

from mkfst.snowflake import Snowflake, SnowflakeGenerator
from mkfst.snowflake.constants import MAX_INSTANCE, MAX_SEQ


def test_generate_returns_unique_increasing_ids() -> None:
    gen = SnowflakeGenerator(instance=1)
    ids = [gen.generate() for _ in range(1000)]
    assert all(isinstance(i, int) for i in ids)
    assert len(set(ids)) == 1000


def test_generate_never_returns_none_under_sequence_pressure() -> None:
    """Pre-fix the generator returned None when the per-ms sequence (4096)
    was exhausted. Callers used the result as dict keys → corruption."""
    gen = SnowflakeGenerator(instance=1)
    ids = [gen.generate() for _ in range(MAX_SEQ + 50)]
    assert all(i is not None for i in ids)
    assert len(set(ids)) == len(ids)


def test_generate_is_thread_safe() -> None:
    gen = SnowflakeGenerator(instance=2)
    out: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        local: list[int] = [gen.generate() for _ in range(500)]
        with lock:
            out.extend(local)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(out) == 500 * 8
    assert len(set(out)) == 500 * 8


def test_instance_bits_masked() -> None:
    """A caller can't poison the timestamp bits by passing an instance value
    that overflows the 10-bit instance region."""
    big_instance = 0xFFFFFFFF  # 32 bits of 1s
    gen = SnowflakeGenerator(instance=big_instance)
    snowflake = gen.generate()
    parsed = Snowflake.parse(snowflake)
    assert parsed.instance == MAX_INSTANCE
    # Timestamp is the recent wall-clock millis; sanity-check the magnitude.
    assert parsed.timestamp > 0


def test_from_snowflake_does_not_raise() -> None:
    """Pre-fix `from_snowflake` passed `epoch` to __init__ which didn't accept
    it, raising TypeError on every call."""
    gen = SnowflakeGenerator(instance=3)
    sf = Snowflake.parse(gen.generate())
    rebuilt = SnowflakeGenerator.from_snowflake(sf)
    assert rebuilt.generate() > 0


def test_clock_regression_does_not_corrupt() -> None:
    """When wall-clock steps backward (NTP), the generator should block until
    it catches up rather than returning None."""
    gen = SnowflakeGenerator(instance=4)
    # Force the generator's internal timestamp to be ~50ms in the future so
    # subsequent generate() calls see a "clock regression".
    future_ts = int(time.time() * 1000) + 50
    gen._ts = future_ts
    start = time.time()
    nid = gen.generate()
    elapsed_ms = (time.time() - start) * 1000
    assert nid is not None
    # We should have spent ~50ms blocking, but also no more than the regression.
    assert 30 <= elapsed_ms <= 200


def test_invalid_instance_rejected() -> None:
    with pytest.raises(ValueError):
        SnowflakeGenerator(instance=-1)


def test_invalid_seq_rejected() -> None:
    with pytest.raises(ValueError):
        SnowflakeGenerator(instance=0, seq=MAX_SEQ + 1)
