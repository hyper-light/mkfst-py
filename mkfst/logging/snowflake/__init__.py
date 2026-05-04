"""Re-export shim. See ``mkfst.tasks.snowflake.__init__`` for the
rationale: a single canonical implementation under ``mkfst.snowflake``
removes the audited divergence between three private copies."""

from mkfst.snowflake import Snowflake, SnowflakeGenerator

__all__ = ["Snowflake", "SnowflakeGenerator"]
