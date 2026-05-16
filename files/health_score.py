"""
StatsFlow Health Score Engine
------------------------------
Computes a multi-dimensional data quality score (0–100) for any DataFrame.

Score Dimensions:
  - Completeness  (40 pts): Proportion of non-null values across all cells.
  - Uniqueness    (20 pts): Penalizes duplicate rows.
  - Consistency   (20 pts): Detects type-mixed object columns.
  - Outlier Score (20 pts): Penalizes columns with high Z-score outlier ratios.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any

from app.services.quality_scorecard import compute_quality_scorecard


def compute_health_score(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Compute a comprehensive data quality health score for the given DataFrame.

    Args:
        df: The DataFrame to evaluate (raw or cleaned).

    Returns:
        A dict with 'total' (0–100) and individual dimension scores.
    """
    if df.empty:
        return {
            "total": 0.0,
            "completeness": 0.0,
            "uniqueness": 100.0,
            "consistency": 100.0,
            "outlier_score": 100.0,
            "missing_cells": 0,
            "total_cells": 0,
            "duplicate_rows": 0,
        }

    total_cells = df.shape[0] * df.shape[1]
    missing_cells = int(df.isnull().sum().sum())
    duplicate_rows = int(df.duplicated().sum())

    # ── Dimension 1: Completeness ─────────────────────────────────────────────
    # Percentage of filled (non-null) cells across the entire dataset
    non_null_cells = total_cells - missing_cells
    completeness = (non_null_cells / total_cells) * 100 if total_cells > 0 else 100.0

    # ── Dimension 2: Uniqueness ───────────────────────────────────────────────
    # Penalizes the proportion of duplicated rows
    duplicate_ratio = duplicate_rows / len(df) if len(df) > 0 else 0.0
    uniqueness = (1 - duplicate_ratio) * 100

    # ── Dimension 3: Consistency ──────────────────────────────────────────────
    # For object (string) columns, detect mixed-type content
    # e.g., a column that is mostly numeric but has some text values
    consistency_scores = []
    for col in df.columns:
        if df[col].dtype == object:
            non_null_vals = df[col].dropna()
            if len(non_null_vals) == 0:
                consistency_scores.append(100.0)
                continue

            # Attempt numeric coercion — a high failure rate indicates inconsistency
            coerced = pd.to_numeric(non_null_vals, errors="coerce")
            numeric_ratio = coerced.notna().sum() / len(non_null_vals)

            # Columns that are purely text OR purely numeric score 100
            # Mixed columns (e.g., 50% numeric, 50% text) score lower
            consistency = 100 - (min(numeric_ratio, 1 - numeric_ratio) * 200)
            consistency_scores.append(max(0.0, consistency))
        else:
            # Typed numeric/datetime columns are fully consistent
            consistency_scores.append(100.0)

    consistency = float(np.mean(consistency_scores)) if consistency_scores else 100.0

    # ── Dimension 4: Outlier Score ────────────────────────────────────────────
    # For each numeric column, measure the proportion of Z-score outliers (|Z| > 3)
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    outlier_details = {}

    if numeric_cols:
        outlier_ratios = []
        for col in numeric_cols:
            col_data = df[col].dropna()
            if len(col_data) < 2:
                outlier_ratios.append(0.0)
                continue

            std = col_data.std()
            if std == 0:
                outlier_ratios.append(0.0)
                continue

            z_scores = np.abs((col_data - col_data.mean()) / std)
            ratio = float((z_scores > 3).sum() / len(col_data))
            outlier_ratios.append(ratio)
            outlier_details[col] = round(ratio * 100, 2)

        avg_outlier_ratio = float(np.mean(outlier_ratios))
        outlier_score = (1 - avg_outlier_ratio) * 100
    else:
        outlier_score = 100.0

    # ── Weighted Composite Score ──────────────────────────────────────────────
    # Weights reflect relative importance of each quality dimension
    total_score = (
        completeness  * 0.40 +   # Completeness is most critical
        uniqueness     * 0.20 +
        consistency    * 0.20 +
        outlier_score  * 0.20
    )

    result = {
        "total": round(total_score, 1),
        "completeness": round(completeness, 1),
        "uniqueness": round(uniqueness, 1),
        "consistency": round(consistency, 1),
        "outlier_score": round(outlier_score, 1),
        "missing_cells": missing_cells,
        "total_cells": total_cells,
        "duplicate_rows": duplicate_rows,
        "outlier_details": outlier_details,
    }

    # Add business-facing scorecard dimensions requested by product.
    quality = compute_quality_scorecard(df)
    result["validity"] = quality["dimensions"].get("validity", 0.0)
    result["timeliness"] = quality["dimensions"].get("timeliness", 0.0)
    result["quality_scorecard"] = quality

    return result


def get_score_label(score: float) -> str:
    """
    Convert a numeric score into a human-readable quality label.

    Args:
        score: Numeric score between 0 and 100.

    Returns:
        Quality label string.
    """
    if score >= 90:
        return "Excellent"
    elif score >= 75:
        return "Good"
    elif score >= 60:
        return "Fair"
    elif score >= 40:
        return "Poor"
    else:
        return "Critical"