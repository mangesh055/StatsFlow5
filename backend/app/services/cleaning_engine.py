"""
StatsFlow Cleaning Engine
--------------------------
Implements statistically valid data cleaning methods:

Missing Value Strategies:
  - mean     : Fill numerics with column mean
  - median   : Fill numerics with column median
  - mode     : Fill all columns with column mode
  - knn      : K-Nearest Neighbors imputation (scikit-learn)
  - drop     : Drop rows with any missing values

Outlier Strategies:
  - zscore   : Replace outliers (|Z|>3) with column median
  - iqr      : Replace values outside [Q1-1.5*IQR, Q3+1.5*IQR] with bounds
  - none     : Skip outlier treatment
"""

import pandas as pd
import numpy as np
from sklearn.impute import KNNImputer
from typing import Dict, Any, Tuple, List
import logging

logger = logging.getLogger(__name__)


MISSING_PLACEHOLDER_TOKENS = {
    "",
    "/",
    "\\",
    "-",
    "--",
    "na",
    "n/a",
    "none",
    "null",
    "nil",
    "nan",
    "?",
    "unknown",
    "d",  # Common error/missing indicator
    "na",  # Additional variations
    "n.a",
    "#n/a",
}


class CleaningEngine:
    """
    Stateful cleaning engine that tracks every operation performed.
    The operations log is used later by the PipelineGenerator to produce
    an exportable, reproducible Python script.
    """

    def __init__(self, df: pd.DataFrame):
        """
        Initialize the engine with a raw DataFrame.

        Args:
            df: The raw, uncleaned dataset.
        """
        self.original_df = df.copy()
        self.df = df.copy()
        self.operations: List[Dict[str, Any]] = []   # Ordered log of all steps
        self.cleaning_report: Dict[str, Any] = {}    # Human-readable report

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def clean(
        self,
        missing_strategy: str = "mean",
        outlier_strategy: str = "iqr",
    ) -> Tuple[pd.DataFrame, Dict[str, Any], List[Dict]]:
        """
        Execute the full cleaning pipeline.

        Args:
            missing_strategy: How to handle missing values.
            outlier_strategy: How to treat statistical outliers.

        Returns:
            Tuple of (cleaned_df, cleaning_report, operations_log)
        """
        logger.info(
            f"Starting cleaning: missing={missing_strategy}, outlier={outlier_strategy}"
        )

        step_log = []

        # ── Step 0: Normalize Placeholder Missing Tokens ────────────────────
        normalized_count = self._normalize_placeholder_missing_values()
        step_log.append({
            "step": 0,
            "operation": "normalize_missing_placeholders",
            "description": f"Converted {normalized_count} placeholder values (e.g., '/', 'NA', '-') to missing values",
            "cells_affected": normalized_count,
        })

        # ── Step 1: Remove Duplicate Rows ─────────────────────────────────────
        dup_removed = self._remove_duplicates()
        step_log.append({
            "step": 1,
            "operation": "remove_duplicates",
            "description": f"Removed {dup_removed} duplicate rows",
            "rows_affected": dup_removed,
        })

        # ── Step 2: Drop Columns with >80% Missing Values ──────────────────
        cols_dropped = self._drop_high_null_columns(threshold=0.80)
        step_log.append({
            "step": 2,
            "operation": "drop_high_null_columns",
            "description": f"Dropped columns with >80% nulls: {cols_dropped}",
            "columns_affected": cols_dropped,
        })

        # ── Step 3: Handle Missing Values ─────────────────────────────────────
        missing_before = int(self.df.isnull().sum().sum())
        imputation_details = self._handle_missing_values(missing_strategy)
        missing_after = int(self.df.isnull().sum().sum())
        step_log.append({
            "step": 3,
            "operation": f"impute_{missing_strategy}",
            "description": f"Imputed {missing_before - missing_after} missing values using '{missing_strategy}' strategy",
            "missing_before": missing_before,
            "missing_after": missing_after,
            "details": imputation_details,
        })

        # ── Step 4: Treat Outliers ────────────────────────────────────────────
        if outlier_strategy != "none":
            outlier_details = self._handle_outliers(outlier_strategy)
            step_log.append({
                "step": 4,
                "operation": f"outlier_{outlier_strategy}",
                "description": f"Treated outliers using '{outlier_strategy}' method",
                "details": outlier_details,
            })
        else:
            step_log.append({
                "step": 4,
                "operation": "outlier_none",
                "description": "Outlier treatment skipped by user choice",
                "details": {},
            })

        # ── Step 5: Reset Index ───────────────────────────────────────────────
        self.df.reset_index(drop=True, inplace=True)
        step_log.append({
            "step": 5,
            "operation": "reset_index",
            "description": "Reset DataFrame index after row removal operations",
        })

        # ── Compile Report ────────────────────────────────────────────────────
        self.operations = step_log
        self.cleaning_report = {
            "original_shape": {
                "rows": int(self.original_df.shape[0]),
                "cols": int(self.original_df.shape[1]),
            },
            "cleaned_shape": {
                "rows": int(self.df.shape[0]),
                "cols": int(self.df.shape[1]),
            },
            "total_rows_removed": int(
                self.original_df.shape[0] - self.df.shape[0]
            ),
            "total_cols_removed": int(
                self.original_df.shape[1] - self.df.shape[1]
            ),
            "missing_strategy": missing_strategy,
            "outlier_strategy": outlier_strategy,
            "steps": step_log,
        }

        return self.df, self.cleaning_report, self.operations

    # ─────────────────────────────────────────────────────────────────────────
    # Private Cleaning Methods
    # ─────────────────────────────────────────────────────────────────────────

    def _remove_duplicates(self) -> int:
        """Remove fully duplicate rows and return the count removed."""
        before = len(self.df)
        self.df.drop_duplicates(inplace=True)
        return before - len(self.df)

    def _normalize_placeholder_missing_values(self) -> int:
        """Convert common placeholder strings like '/' and 'NA' into NaN.
        
        Also attempts to intelligently convert object columns to numeric types
        and treats non-convertible values as missing.
        """
        object_cols = self.df.select_dtypes(include=["object", "category"]).columns.tolist()
        replaced = 0

        for col in object_cols:
            series = self.df[col]
            as_str = series.astype(str).str.strip()
            as_lower = as_str.str.lower()

            # Step 1: Replace known placeholder tokens with NaN
            mask_placeholder = as_lower.isin(MISSING_PLACEHOLDER_TOKENS)
            mask_existing_missing = series.isnull()
            mask = mask_placeholder | mask_existing_missing
            
            replaced += int(mask_placeholder.sum())
            self.df.loc[mask, col] = np.nan
            
            # Step 2: Try to intelligently convert to numeric if column looks numeric
            self._try_coerce_to_numeric(col)

        return replaced
    
    def _try_coerce_to_numeric(self, col: str) -> None:
        """Attempt to convert a column to numeric type.
        
        If the column contains mostly numeric values but some non-numeric strings,
        convert the column to numeric (coercing non-numeric values to NaN).
        """
        series = self.df[col]
        
        # Skip if already numeric
        if pd.api.types.is_numeric_dtype(series):
            return
        
        # Skip if all values are non-numeric (likely categorical)
        nulls = series.isnull().sum()
        non_null = series.dropna()
        if non_null.empty:
            return
        
        # Try to convert to numeric
        numeric_series = pd.to_numeric(non_null, errors='coerce')
        numeric_ratio = numeric_series.notna().sum() / len(non_null)
        
        # If >70% of values are successfully numeric, convert the whole column
        if numeric_ratio > 0.70:
            self.df[col] = pd.to_numeric(series, errors='coerce')

    def _best_categorical_fill_value(self, series: pd.Series) -> str:
        """Choose a robust fill value for categorical columns."""
        clean = series.dropna().astype(str).str.strip()
        if clean.empty:
            return "Unknown"

        # Exclude obvious placeholder tokens from fill candidates.
        lowered = clean.str.lower()
        valid = clean[~lowered.isin(MISSING_PLACEHOLDER_TOKENS)]
        if valid.empty:
            return "Unknown"

        # Normalize case/spacing for stable mode selection.
        normalized = valid.str.replace(r"\s+", " ", regex=True)
        mode_vals = normalized.mode()
        if mode_vals.empty:
            return "Unknown"
        return str(mode_vals.iloc[0])

    def _drop_high_null_columns(self, threshold: float = 0.80) -> List[str]:
        """
        Drop columns where the proportion of missing values exceeds `threshold`.

        Args:
            threshold: Float between 0 and 1 (e.g., 0.80 = 80%).

        Returns:
            List of dropped column names.
        """
        null_ratio = self.df.isnull().mean()
        cols_to_drop = null_ratio[null_ratio > threshold].index.tolist()
        self.df.drop(columns=cols_to_drop, inplace=True)
        return cols_to_drop

    def _handle_missing_values(self, strategy: str) -> Dict[str, Any]:
        """
        Impute missing values according to the chosen strategy.

        Args:
            strategy: One of 'mean', 'median', 'mode', 'knn', 'drop', 'ai_impute', 'none'.

        Returns:
            Dict with per-column imputation details.
        """
        if strategy in ("ai_impute", "none"):
            # If AI impute was chosen, the missing values were already filled outside the engine.
            return {"strategy": strategy, "details": "Handled externally"}
            
        numeric_cols = self.df.select_dtypes(include=[np.number]).columns.tolist()
        categorical_cols = self.df.select_dtypes(
            include=["object", "category"]
        ).columns.tolist()
        details = {}

        if strategy == "drop":
            before = len(self.df)
            self.df.dropna(inplace=True)
            details["rows_dropped"] = before - len(self.df)
            return details

        if strategy == "knn" and numeric_cols:
            # KNN imputation only on numeric columns
            imputer = KNNImputer(n_neighbors=5)
            numeric_data = self.df[numeric_cols]
            imputed_values = imputer.fit_transform(numeric_data)
            self.df[numeric_cols] = imputed_values
            details["knn_columns"] = numeric_cols
            details["k_neighbors"] = 5
        else:
            # Mean / Median / Mode imputation
            for col in numeric_cols:
                if self.df[col].isnull().any():
                    if strategy == "mean":
                        fill_value = self.df[col].mean()
                    elif strategy == "median":
                        fill_value = self.df[col].median()
                    else:  # mode (fallback)
                        mode_vals = self.df[col].mode()
                        fill_value = mode_vals[0] if not mode_vals.empty else 0

                    self.df[col].fillna(fill_value, inplace=True)
                    details[col] = {"strategy": strategy, "fill_value": round(float(fill_value), 4)}

        # Always fill categorical columns with mode
        for col in categorical_cols:
            if self.df[col].isnull().any():
                fill_value = self._best_categorical_fill_value(self.df[col])
                self.df[col].fillna(fill_value, inplace=True)
                details[col] = {"strategy": "mode", "fill_value": str(fill_value)}

        return details

    def _handle_outliers(self, strategy: str) -> Dict[str, Any]:
        """
        Detect and treat outliers in numeric columns.

        Args:
            strategy: One of 'zscore' or 'iqr'.

        Returns:
            Dict with per-column outlier treatment details.
        """
        numeric_cols = self.df.select_dtypes(include=[np.number]).columns.tolist()
        details = {}

        for col in numeric_cols:
            col_data = self.df[col].dropna()
            if len(col_data) < 4:
                continue  # Not enough data to assess outliers

            if strategy == "zscore":
                mean = col_data.mean()
                std = col_data.std()
                if std == 0:
                    continue

                z_scores = (self.df[col] - mean) / std
                outlier_mask = z_scores.abs() > 3
                count = int(outlier_mask.sum())

                if count > 0:
                    median = col_data.median()
                    self.df.loc[outlier_mask, col] = median
                    details[col] = {
                        "method": "zscore",
                        "outliers_found": count,
                        "replaced_with": "median",
                        "median_value": round(float(median), 4),
                    }

            elif strategy == "iqr":
                q1 = col_data.quantile(0.25)
                q3 = col_data.quantile(0.75)
                iqr = q3 - q1

                if iqr == 0:
                    continue

                lower_bound = q1 - 1.5 * iqr
                upper_bound = q3 + 1.5 * iqr

                lower_mask = self.df[col] < lower_bound
                upper_mask = self.df[col] > upper_bound
                count = int((lower_mask | upper_mask).sum())

                if count > 0:
                    # Cap values at the IQR bounds (Winsorization)
                    self.df[col] = self.df[col].clip(
                        lower=lower_bound, upper=upper_bound
                    )
                    details[col] = {
                        "method": "iqr",
                        "outliers_found": count,
                        "lower_bound": round(float(lower_bound), 4),
                        "upper_bound": round(float(upper_bound), 4),
                        "action": "capped_at_bounds",
                    }

        return details