"""
Data Quality Scorecard Service
------------------------------
Computes a session-level quality scorecard with business-facing dimensions:
- completeness
- validity
- uniqueness
- timeliness
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import numpy as np
import pandas as pd

MISSING_TOKENS = {"", "na", "n/a", "null", "none", "nan", "missing", "unknown"}


def _safe_pct(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 100.0
    return max(0.0, min(100.0, (numerator / denominator) * 100.0))


def _as_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _candidate_datetime_series(series: pd.Series) -> pd.Series:
    """Try to parse a column as datetimes while preserving NaNs."""
    try:
        if pd.api.types.is_datetime64_any_dtype(series):
            # If it's already a datetime but tz-aware, converting to utc=True can fail in some pandas versions
            # if we don't coerce properly, but we'll try to convert it.
            if series.dt.tz is not None:
                return series.dt.tz_convert('UTC')
            return series.dt.tz_localize('UTC')

        return pd.to_datetime(series, errors="coerce", utc=True)
    except Exception:
        return pd.Series([pd.NaT] * len(series), index=series.index)


def _validity_for_column(col_name: str, series: pd.Series) -> Dict[str, Any]:
    non_null = series.dropna()
    if non_null.empty:
        return {
            "column": col_name,
            "validity": 100.0,
            "checks": {"non_null": 0, "valid": 0, "invalid": 0},
        }

    if pd.api.types.is_numeric_dtype(series):
        as_num = pd.to_numeric(non_null, errors="coerce")
        valid_mask = np.isfinite(as_num)

        # Domain checks for EDI-like transactional fields.
        lower_name = col_name.lower()
        if any(k in lower_name for k in ["price", "amount", "cost", "qty", "quantity", "units", "total"]):
            valid_mask = valid_mask & (as_num >= 0)

        valid_count = int(valid_mask.sum())
        total = int(len(non_null))
        return {
            "column": col_name,
            "validity": round(_safe_pct(valid_count, total), 2),
            "checks": {"non_null": total, "valid": valid_count, "invalid": total - valid_count},
        }

    as_dt = _candidate_datetime_series(non_null)
    dt_parse_ratio = as_dt.notna().mean() if len(non_null) else 0.0
    if dt_parse_ratio >= 0.70:
        now = _as_utc_now()
        non_future = (as_dt <= now).sum()
        parsed = int(as_dt.notna().sum())
        valid_count = int(non_future)
        total = int(len(non_null))
        return {
            "column": col_name,
            "validity": round(_safe_pct(valid_count, total), 2),
            "checks": {
                "non_null": total,
                "parsed_datetime": parsed,
                "non_future": valid_count,
                "invalid": total - valid_count,
            },
        }

    normalized = non_null.astype(str).str.strip().str.lower()
    valid_mask = ~normalized.isin(MISSING_TOKENS)
    valid_count = int(valid_mask.sum())
    total = int(len(non_null))
    return {
        "column": col_name,
        "validity": round(_safe_pct(valid_count, total), 2),
        "checks": {"non_null": total, "valid": valid_count, "invalid": total - valid_count},
    }


def _timeliness_score(df: pd.DataFrame) -> Dict[str, Any]:
    """Compute freshness/timeliness from detected datetime columns."""
    candidate_cols: List[str] = []
    column_scores: List[float] = []
    details: List[Dict[str, Any]] = []

    now = _as_utc_now()

    for col in df.columns:
        series = df[col]
        parsed = _candidate_datetime_series(series.dropna())
        if parsed.empty:
            continue

        parse_ratio = parsed.notna().mean()
        if parse_ratio < 0.70 and not pd.api.types.is_datetime64_any_dtype(series):
            continue

        candidate_cols.append(col)
        parsed_values = parsed.dropna()
        if parsed_values.empty:
            details.append({"column": col, "timeliness": 0.0, "reason": "no parseable datetime values"})
            column_scores.append(0.0)
            continue

        future_ratio = float((parsed_values > now).mean())
        median_age_days = float((now - parsed_values.median()).total_seconds() / 86400.0)
        median_age_days = max(0.0, median_age_days)

        # Freshness curve: 100 at 0 days, decays to 40 by 5 years.
        freshness_component = max(40.0, 100.0 - min(60.0, (median_age_days / 365.0) * 12.0))
        non_future_component = (1.0 - future_ratio) * 100.0
        score = (freshness_component * 0.6) + (non_future_component * 0.4)

        details.append(
            {
                "column": col,
                "timeliness": round(score, 2),
                "parse_ratio": round(float(parse_ratio * 100), 2),
                "future_ratio": round(float(future_ratio * 100), 2),
                "median_age_days": round(median_age_days, 2),
            }
        )
        column_scores.append(score)

    if not candidate_cols:
        return {
            "score": 75.0,
            "has_datetime_columns": False,
            "details": [],
            "note": "No datetime columns detected; timeliness set to neutral baseline.",
        }

    return {
        "score": round(float(np.mean(column_scores)), 2),
        "has_datetime_columns": True,
        "details": details,
    }


def compute_quality_scorecard(df: pd.DataFrame) -> Dict[str, Any]:
    """Return a business-facing quality scorecard for a DataFrame."""
    if df is None or df.empty:
        return {
            "total": 0.0,
            "label": "Critical",
            "dimensions": {
                "completeness": 0.0,
                "validity": 0.0,
                "uniqueness": 0.0,
                "timeliness": 0.0,
            },
            "weights": {
                "completeness": 0.35,
                "validity": 0.30,
                "uniqueness": 0.20,
                "timeliness": 0.15,
            },
            "details": {
                "missing_cells": 0,
                "total_cells": 0,
                "duplicate_rows": 0,
                "validity_by_column": [],
                "timeliness": {
                    "score": 0.0,
                    "has_datetime_columns": False,
                    "details": [],
                },
            },
        }

    total_cells = int(df.shape[0] * df.shape[1])
    missing_cells = int(df.isnull().sum().sum())
    duplicate_rows = int(df.duplicated().sum())

    completeness = _safe_pct(total_cells - missing_cells, total_cells)
    uniqueness = _safe_pct(len(df) - duplicate_rows, len(df))

    validity_details = [_validity_for_column(col, df[col]) for col in df.columns]
    validity = float(np.mean([item["validity"] for item in validity_details])) if validity_details else 100.0

    timeliness_data = _timeliness_score(df)
    timeliness = float(timeliness_data["score"])

    weights = {
        "completeness": 0.35,
        "validity": 0.30,
        "uniqueness": 0.20,
        "timeliness": 0.15,
    }

    total_score = (
        completeness * weights["completeness"]
        + validity * weights["validity"]
        + uniqueness * weights["uniqueness"]
        + timeliness * weights["timeliness"]
    )

    return {
        "total": round(total_score, 1),
        "label": _score_label(total_score),
        "dimensions": {
            "completeness": round(completeness, 1),
            "validity": round(validity, 1),
            "uniqueness": round(uniqueness, 1),
            "timeliness": round(timeliness, 1),
        },
        "weights": weights,
        "details": {
            "missing_cells": missing_cells,
            "total_cells": total_cells,
            "duplicate_rows": duplicate_rows,
            "validity_by_column": validity_details,
            "timeliness": timeliness_data,
        },
    }


def _score_label(score: float) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Fair"
    if score >= 40:
        return "Poor"
    return "Critical"
