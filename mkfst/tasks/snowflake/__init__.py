"""Re-export shim. Canonical implementation lives in ``mkfst.snowflake``;
the prior in-tree copies had subtle differences (missing instance masking,
``None`` returns on overflow). Forwarding to a single source of truth
eliminates that class of bug."""

from mkfst.snowflake import Snowflake, SnowflakeGenerator

__all__ = ["Snowflake", "SnowflakeGenerator"]
