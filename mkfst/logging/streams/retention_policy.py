import datetime
import glob
import os
import pathlib
import re
from typing import Dict, Literal

from mkfst.logging.rotation import (
    FileSizeParser,
    TimeParser,
)

RetentionPolicyConfig = Dict[Literal["max_age", "rotation_time", "max_size"], str]

ParsedRetentionPolicyConfig = Dict[
    Literal["max_age", "rotation_time", "max_size"], int | float | str
]

CheckState = Dict[Literal["max_age", "rotation_time", "max_size"], bool]

PolicyQuery = Dict[
    Literal["file_age", "file_size", "logfile_path"], int | float | pathlib.Path
]


def get_timestamp(filenamne: str):
    if match := re.match(r"[+-]?([0-9]*[.])?[0-9]+", filenamne):
        return float(match.group(0))

    return 0


class RetentionPolicy:
    def __init__(self, retention_policy: RetentionPolicyConfig) -> None:
        self._retention_policy = retention_policy
        self._parsed_policy: ParsedRetentionPolicyConfig = {}

        self._time_parser = TimeParser()
        self._file_size_parser = FileSizeParser()

    def parse(self):
        if max_age := self._retention_policy.get("max_age"):
            self._parsed_policy["max_age"] = self._time_parser.parse(max_age)

        if max_size := self._retention_policy.get("max_size"):
            self._parsed_policy["max_size"] = self._file_size_parser.parse(max_size)

        if rotation_time := self._retention_policy.get("rotation_time"):
            self._parsed_policy["rotation_time"] = rotation_time

    def matches_policy(
        self,
        policy_query: PolicyQuery,
    ) -> bool:
        """Return True iff the file is currently within every configured
        retention limit. Caller rotates when this returns False.

        Pre-fix the comparison was
        ``len(passing_checks) >= len(self._parsed_policy)`` with
        ``passing_checks`` initialized to True for *all three* possible
        check kinds. With only one policy configured (e.g. ``max_size``)
        the two unused checks stayed True; the count was always at least
        2 ≥ 1, so the function always returned True and rotation never
        fired.
        """
        resolved_path: pathlib.Path = policy_query["logfile_path"]
        logfile_directory = str(resolved_path.parent.absolute().resolve())

        max_age = self._parsed_policy.get("max_age")
        if max_age is not None:
            file_age = policy_query.get("file_age", 0)
            if file_age >= max_age:
                return False

        max_file_size = self._parsed_policy.get("max_size")
        if max_file_size is not None:
            file_size = policy_query.get("file_size", 0)
            if file_size >= max_file_size:
                return False

        rotation_time = self._parsed_policy.get("rotation_time")
        if rotation_time is not None:
            current_time = datetime.datetime.now()
            current_time_string = current_time.strftime("%H:%M")
            if rotation_time == current_time_string:
                # Wall-clock hit the rotation slot; check we haven't
                # already rotated in this slot to avoid back-to-back
                # archives.
                existing_logfiles = glob.glob(
                    os.path.join(
                        logfile_directory,
                        f"{resolved_path.stem}_*_archived.zst",
                    )
                )
                last_archived: datetime.datetime | None = None
                if existing_logfiles:
                    last_archived = datetime.datetime.fromtimestamp(
                        os.path.getmtime(
                            max(existing_logfiles, key=os.path.getmtime)
                        ),
                    )
                if (
                    last_archived is None
                    or (current_time - last_archived).total_seconds() >= 60
                ):
                    return False

        return True
