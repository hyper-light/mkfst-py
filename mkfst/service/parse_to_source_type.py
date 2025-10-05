from typing import Any, get_origin


def parse_to_source_type(pattern: Any):
    try:
        return get_origin(pattern) or pattern

    except Exception:
        pass
