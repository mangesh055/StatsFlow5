"""
StatsFlow Utilities Package
----------------------------
Shared helper functions used across routers, services, and models.

Exports:
  - generate_session_id : UUID4 session identifier generator
  - safe_path           : Filesystem path builder for session files
  - df_to_json_safe     : DataFrame → JSON-serializable list (NaN-safe)
  - get_column_types    : Classify each column as numeric/categorical/datetime
  - describe_dataframe  : Rich statistical summary dict for LLM context
  - _convert_types      : Recursive numpy→Python type converter
"""

from app.utils.helpers import (
    generate_session_id,
    safe_path,
    df_to_json_safe,
    get_column_types,
    describe_dataframe,
    _convert_types,
)

__all__ = [
    "generate_session_id",
    "safe_path",
    "df_to_json_safe",
    "get_column_types",
    "describe_dataframe",
    "_convert_types",
]