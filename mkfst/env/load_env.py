import os
import msgspec
from typing import Dict, Type, TypeVar, Union

from dotenv import dotenv_values

from .env import Env

T = TypeVar("T", bound=msgspec.Struct)

PrimaryType = Union[str, int, bool, float, bytes]


def load_env(default: type[Env], env_file: str = None, override: T | None = None) -> T:
    envars = default.types_map()

    if env_file is None:
        env_file = ".env"

    # Standard precedence (highest → lowest): runtime override → process
    # environment → .env file → schema defaults. Pre-fix the .env file
    # overrode the process environment, which broke the common operator
    # pattern of using shell exports to override a checked-in .env.
    values: Dict[str, PrimaryType] = {}

    if env_file and os.path.exists(env_file):
        env_file_values = dotenv_values(dotenv_path=env_file)
        for envar_name, envar_value in env_file_values.items():
            envar_type = envars.get(envar_name)
            if envar_type and envar_value is not None:
                values[envar_name] = envar_type(envar_value)

    for envar_name, envar_type in envars.items():
        envar_value = os.getenv(envar_name)
        if envar_value:
            values[envar_name] = envar_type(envar_value)

    if override:
        values.update(**msgspec.structs.asdict(override))

        return type(override)(
            **{name: value for name, value in values.items() if value is not None}
        )

    return default(
        **{name: value for name, value in values.items() if value is not None}
    )
