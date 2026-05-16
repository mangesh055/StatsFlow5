"""
StatsFlow Helper Utilities
---------------------------
Reusable utility functions shared across the application.
"""

import uuid
import os
import math
import pandas as pd
import numpy as np
from typing import Any, Dict, List
from datetime import datetime


def generate_session_id() -> str:
    """Generate a cryptographically unique session identifier (UUID4)."""
    return str(uuid.uuid4())


def safe_path(directory: str, session_id: str, suffix: str) -> str:
    """
    Construct a safe filesystem path for session files.

    Args:
        directory: Base upload directory.
        session_id: Unique session identifier.
        suffix: File suffix/tag (e.g., 'raw', 'cleaned').

    Returns:
        Full filesystem path string.
    """
    return os.path.join(directory, f"{session_id}_{suffix}.csv")


def df_to_json_safe(df: pd.DataFrame, max_rows: int = 100) -> List[Dict]:
    """
    Convert a DataFrame to a JSON-serializable list of dicts.
    Handles NaN, Inf, and numpy type conversion safely.

    Args:
        df: Source DataFrame.
        max_rows: Maximum rows to include (prevents payload bloat).

    Returns:
        List of row dicts with Python-native types.
    """
    sample = df.head(max_rows).copy()

    # Replace non-JSON-compliant float values
    sample = sample.replace([np.inf, -np.inf], None)
    sample = sample.where(pd.notnull(sample), None)

    records = sample.to_dict(orient="records")

    # Recursively convert numpy types to Python native types
    return [_convert_types(row) for row in records]


def _convert_types(obj: Any) -> Any:
    """
    Recursively convert numpy/pandas types to JSON-serializable Python types.
    """
    if isinstance(obj, dict):
        return {k: _convert_types(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_types(v) for v in obj]
    elif isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        val = float(obj)
        return None if (np.isnan(val) or np.isinf(val)) else val
    elif isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    elif isinstance(obj, datetime):
        return obj.isoformat()
    else:
        return obj


def get_column_types(df: pd.DataFrame) -> Dict[str, str]:
    """
    Classify each column as 'numeric', 'categorical', or 'datetime'.

    Args:
        df: Source DataFrame.

    Returns:
        Dict mapping column name → type string.
    """
    col_types = {}
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            col_types[col] = "numeric"
        elif pd.api.types.is_datetime64_any_dtype(df[col]):
            col_types[col] = "datetime"
        else:
            col_types[col] = "categorical"
    return col_types


def describe_dataframe(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Generate a rich statistical summary of a DataFrame.
    Used for chatbot context injection.

    Args:
        df: Source DataFrame.

    Returns:
        Dict containing shape, dtypes, missing counts, and numeric stats.
    """
    numeric_df = df.select_dtypes(include=[np.number])
    stats = {}

    if not numeric_df.empty:
        desc = numeric_df.describe().to_dict()
        stats = _convert_types(desc)

    return {
        "shape": {"rows": int(df.shape[0]), "columns": int(df.shape[1])},
        "columns": list(df.columns),
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "missing_values": _convert_types(df.isnull().sum().to_dict()),
        "numeric_stats": stats,
        "sample_rows": df_to_json_safe(df, max_rows=5),
    }