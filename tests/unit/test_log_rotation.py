"""Regression coverage for the audited logging-rotation defects.

* ``RetentionPolicy.matches_policy`` returned True when *fewer* configured
  policies were breached than the total possible policies — so a server
  that configured only ``max_size`` would never rotate even when the size
  limit was breached.
* ``_update_logfile_metadata`` opened the metadata file with mode
  ``+wb`` which truncates first; a process crash between truncate and
  write left an empty ``.logging.json`` and the rotator lost track of the
  file's creation time on the next read.
* ``_get_logfile_metadata`` opened the metadata file but never closed it.
* ``_rotate_logfile`` left the live log file's handle closed when an
  archive wasn't produced; subsequent writes hit a closed FD.
"""

from __future__ import annotations

import datetime
import os
import pathlib

import pytest

import zstandard

from mkfst.logging.streams.logger_stream import LoggerStream
from mkfst.logging.streams.retention_policy import RetentionPolicy


def _policy(**parsed) -> RetentionPolicy:
    p = RetentionPolicy({})
    p._parsed_policy = dict(parsed)
    return p


def test_size_only_policy_breach_triggers_rotation(tmp_path: pathlib.Path) -> None:
    """Single-policy size breach must return False (= rotate)."""
    policy = _policy(max_size=100)
    breach = policy.matches_policy(
        {
            "file_age": 0,
            "file_size": 200,  # exceeds 100
            "logfile_path": tmp_path / "app.log",
        }
    )
    assert breach is False


def test_size_only_policy_within_limit_does_not_rotate(tmp_path: pathlib.Path) -> None:
    policy = _policy(max_size=100)
    within = policy.matches_policy(
        {
            "file_age": 0,
            "file_size": 50,
            "logfile_path": tmp_path / "app.log",
        }
    )
    assert within is True


def test_age_only_policy_breach_triggers_rotation(tmp_path: pathlib.Path) -> None:
    policy = _policy(max_age=60)
    assert (
        policy.matches_policy(
            {
                "file_age": 120,
                "file_size": 0,
                "logfile_path": tmp_path / "app.log",
            }
        )
        is False
    )


def test_combined_policy_either_breach_triggers(tmp_path: pathlib.Path) -> None:
    policy = _policy(max_age=60, max_size=100)
    # age breach
    assert (
        policy.matches_policy({"file_age": 120, "file_size": 50, "logfile_path": tmp_path / "x"})
        is False
    )
    # size breach
    assert (
        policy.matches_policy({"file_age": 30, "file_size": 999, "logfile_path": tmp_path / "x"})
        is False
    )
    # both within
    assert (
        policy.matches_policy({"file_age": 30, "file_size": 50, "logfile_path": tmp_path / "x"})
        is True
    )


def test_metadata_write_is_atomic(tmp_path: pathlib.Path) -> None:
    """Replace the existing .logging.json without ever leaving an empty
    file behind. Pre-fix the writer used `+wb` which truncates first."""
    stream = LoggerStream(name="test")
    target = tmp_path / "app.log"
    metadata_path = tmp_path / ".logging.json"

    # Seed an existing payload so we can detect truncation.
    metadata_path.write_bytes(b'{"existing": 1.0}')

    stream._update_logfile_metadata(str(target), {"new": 2.0})

    # The file must always be a complete JSON document — never empty.
    written = metadata_path.read_bytes()
    assert written
    import msgspec

    decoded = msgspec.json.decode(written)
    assert decoded == {"new": 2.0}


def test_metadata_read_handles_missing_file(tmp_path: pathlib.Path) -> None:
    stream = LoggerStream(name="test")
    target = tmp_path / "app.log"
    assert stream._get_logfile_metadata(str(target)) == {}


def test_metadata_read_tolerates_corrupt_file(tmp_path: pathlib.Path) -> None:
    """A concurrent rotator might leave us reading a half-written
    metadata file. The reader must degrade to an empty mapping rather
    than crashing the writer that triggered the read."""
    stream = LoggerStream(name="test")
    target = tmp_path / "app.log"
    (tmp_path / ".logging.json").write_bytes(b"\x00\x01not-json")
    assert stream._get_logfile_metadata(str(target)) == {}


def test_rotate_breach_produces_archive_and_keeps_writer_live(
    tmp_path: pathlib.Path,
) -> None:
    """End-to-end: a size-breach should compress the file into a sibling
    .zst archive, truncate the original, and leave a writable handle so
    subsequent log lines don't go to a closed FD."""
    log_path = tmp_path / "app.log"
    log_path.write_bytes(b"some log line\n" * 50)

    stream = LoggerStream(name="test")
    stream._compressor = zstandard.ZstdCompressor()

    # Open the file the way the stream normally does so the rotator has a
    # handle to flush + close.
    stream._files[str(log_path)] = open(log_path, "ab+")

    policy = _policy(max_size=10)  # current size > 10 → breach
    stream._rotate_logfile(policy, str(log_path))

    # Archive present, original truncated.
    archives = list(tmp_path.glob("app_*_archived.zst"))
    assert len(archives) == 1, archives
    assert log_path.read_bytes() == b""

    # Writer is still live.
    handle = stream._files[str(log_path)]
    assert not handle.closed
    handle.write(b"after rotation\n")
    handle.flush()
    handle.close()
    assert b"after rotation" in log_path.read_bytes()


def test_rotate_within_limits_is_a_noop(tmp_path: pathlib.Path) -> None:
    log_path = tmp_path / "app.log"
    log_path.write_bytes(b"x")

    stream = LoggerStream(name="test")
    stream._compressor = zstandard.ZstdCompressor()
    stream._files[str(log_path)] = open(log_path, "ab+")

    policy = _policy(max_size=1024 * 1024)  # well above 1 byte
    stream._rotate_logfile(policy, str(log_path))

    assert not list(tmp_path.glob("app_*_archived.zst"))
    assert log_path.read_bytes() == b"x"
    handle = stream._files[str(log_path)]
    assert not handle.closed
    handle.close()


def test_rotate_writes_metadata_atomically(tmp_path: pathlib.Path) -> None:
    """The metadata file must always be readable as JSON during/after a
    rotate. Pre-fix the truncate-then-write window left it empty."""
    log_path = tmp_path / "app.log"
    log_path.write_bytes(b"y" * 200)

    stream = LoggerStream(name="test")
    stream._compressor = zstandard.ZstdCompressor()
    stream._files[str(log_path)] = open(log_path, "ab+")

    policy = _policy(max_size=10)
    stream._rotate_logfile(policy, str(log_path))

    metadata_path = tmp_path / ".logging.json"
    assert metadata_path.exists()
    import msgspec

    decoded = msgspec.json.decode(metadata_path.read_bytes())
    assert str(log_path) in decoded
    stream._files[str(log_path)].close()
