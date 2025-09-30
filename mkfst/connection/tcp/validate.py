from re import Pattern
from typing import Any


def validate(
    regex: Pattern[bytes], data: bytes, msg: str = "malformed data", *format_args: Any
) -> dict[str, bytes]:
    match = regex.fullmatch(data)
    
    if not match:
        if format_args:
            msg = msg.format(*format_args)

        raise Exception(msg)
    
    return match.groupdict()
