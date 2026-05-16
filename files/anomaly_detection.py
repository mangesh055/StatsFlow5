"""
Anomaly Detection Service
-------------------------
Detects:
- unusual value distributions
- sudden null spikes (raw -> cleaned)
- outlier price/quantity changes
- partner drift
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

PARTNER_HINTS = ["partner", "supplier", "vendor", "customer", "client", "account", "company", "trading"]
PRICE_QTY_HINTS = ["price", "amount", "cost", "qty", "quantity", "units", "total", "rate"]


def _iqr_outlier_ratio(series: pd.Series) -> float:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < 8:
        return 0.0
    q1, q3 = s.quantile([0.25, 0.75]).tolist()
    iqr = q3 - q1
    if iqr == 0:
        return 0.0
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    return float(((s < lower) | (s > upper)).mean())


def detect_partner_column(df: pd.DataFrame) -> Optional[str]:
    for col in df.columns:
        name = col.lower()
        if any(h in name for h in PARTNER_HINTS):
            return col
    return None


def build_partner_profile(df: pd.DataFrame, partner_col: Optional[str] = None) -> Optional[Dict[str, float]]:
    if df is None or df.empty:
        return None

    partner_col = partner_col or detect_partner_column(df)
    if not partner_col or partner_col not in df.columns:
        return None

    counts = (
        df[partner_col]
        .dropna()
        .astype(str)
        .str.strip()
        .replace("", np.nan)
        .dropna()
        .value_counts(normalize=True)
        .head(20)
    )

    if counts.empty:
        return None

    return {str(k): float(v) for k, v in counts.items()}


def _distribution_anomalies(df: pd.DataFrame) -> List[Dict[str, Any]]:
    anomalies: List[Dict[str, Any]] = []

    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    for col in numeric_cols[:20]:
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(s) < 20:
            continue

        skew = float(s.skew()) if len(s) > 2 else 0.0
        kurt = float(s.kurtosis()) if len(s) > 3 else 0.0

        if abs(skew) > 2.0 or abs(kurt) > 7.0:
            anomalies.append(
                {
                    "type": "unusual_distribution",
                    "severity": "medium" if abs(skew) < 3.0 else "high",
                    "column": col,
                    "message": (
                        f"Column '{col}' shows heavy-tail or skew behavior "
                        f"(skew={skew:.2f}, kurtosis={kurt:.2f})."
                    ),
                    "metrics": {"skew": round(skew, 3), "kurtosis": round(kurt, 3)},
                }
            )

    categorical_cols = [c for c in df.columns if c not in numeric_cols]
    for col in categorical_cols[:20]:
        value_counts = df[col].dropna().astype(str).value_counts(normalize=True)
        if value_counts.empty:
            continue

        top_share = float(value_counts.iloc[0])
        if top_share >= 0.90 and value_counts.shape[0] > 1:
            anomalies.append(
                {
                    "type": "unusual_distribution",
                    "severity": "medium",
                    "column": col,
                    "message": f"Column '{col}' is highly dominated by one category ({top_share * 100:.1f}%).",
                    "metrics": {"top_category_share_pct": round(top_share * 100, 2)},
                }
            )

    return anomalies


def _null_spike_anomalies(raw_df: pd.DataFrame, cleaned_df: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    anomalies: List[Dict[str, Any]] = []
    if raw_df is None or raw_df.empty:
        return anomalies

    if cleaned_df is None or cleaned_df.empty:
        # Baseline warning mode when cleaned frame is unavailable.
        for col in raw_df.columns:
            pct = float(raw_df[col].isna().mean() * 100)
            if pct >= 40.0:
                anomalies.append(
                    {
                        "type": "null_spike",
                        "severity": "medium",
                        "column": col,
                        "message": f"Column '{col}' has high null density ({pct:.1f}%).",
                        "metrics": {"null_pct": round(pct, 2)},
                    }
                )
        return anomalies

    common_cols = [c for c in raw_df.columns if c in cleaned_df.columns]
    for col in common_cols:
        raw_null = float(raw_df[col].isna().mean() * 100)
        cleaned_null = float(cleaned_df[col].isna().mean() * 100)
        delta = cleaned_null - raw_null

        if delta >= 5.0:
            anomalies.append(
                {
                    "type": "null_spike",
                    "severity": "high" if delta >= 10.0 else "medium",
                    "column": col,
                    "message": (
                        f"Null spike detected in '{col}': {raw_null:.1f}% -> {cleaned_null:.1f}% "
                        f"(+{delta:.1f}pp)."
                    ),
                    "metrics": {
                        "raw_null_pct": round(raw_null, 2),
                        "cleaned_null_pct": round(cleaned_null, 2),
                        "delta_pp": round(delta, 2),
                    },
                }
            )

    return anomalies


def _price_quantity_outlier_changes(raw_df: pd.DataFrame, cleaned_df: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    anomalies: List[Dict[str, Any]] = []
    if raw_df is None or raw_df.empty or cleaned_df is None or cleaned_df.empty:
        return anomalies

    for col in raw_df.columns:
        if col not in cleaned_df.columns:
            continue

        lower = col.lower()
        if not any(h in lower for h in PRICE_QTY_HINTS):
            continue

        raw_ratio = _iqr_outlier_ratio(raw_df[col])
        cleaned_ratio = _iqr_outlier_ratio(cleaned_df[col])
        delta_ratio = cleaned_ratio - raw_ratio

        raw_med = pd.to_numeric(raw_df[col], errors="coerce").median()
        clean_med = pd.to_numeric(cleaned_df[col], errors="coerce").median()
        if pd.isna(raw_med) or raw_med == 0 or pd.isna(clean_med):
            median_shift = 0.0
        else:
            median_shift = float(abs(clean_med - raw_med) / abs(raw_med))

        if abs(delta_ratio) >= 0.08 or median_shift >= 0.25:
            anomalies.append(
                {
                    "type": "outlier_change",
                    "severity": "high" if median_shift >= 0.40 else "medium",
                    "column": col,
                    "message": (
                        f"'{col}' changed significantly after cleaning: outlier ratio "
                        f"{raw_ratio * 100:.1f}% -> {cleaned_ratio * 100:.1f}% and median shift {median_shift * 100:.1f}%."
                    ),
                    "metrics": {
                        "raw_outlier_pct": round(raw_ratio * 100, 2),
                        "cleaned_outlier_pct": round(cleaned_ratio * 100, 2),
                        "delta_outlier_pp": round(delta_ratio * 100, 2),
                        "median_shift_pct": round(median_shift * 100, 2),
                    },
                }
            )

    return anomalies


def _distribution_distance(current_profile: Dict[str, float], baseline_profile: Dict[str, float]) -> float:
    keys = set(current_profile.keys()) | set(baseline_profile.keys())
    if not keys:
        return 0.0
    return 0.5 * sum(abs(current_profile.get(k, 0.0) - baseline_profile.get(k, 0.0)) for k in keys)


def _partner_drift_anomalies(
    current_df: pd.DataFrame,
    baseline_profile: Optional[Dict[str, float]] = None,
    partner_col: Optional[str] = None,
) -> List[Dict[str, Any]]:
    anomalies: List[Dict[str, Any]] = []

    partner_col = partner_col or detect_partner_column(current_df)
    if not partner_col or partner_col not in current_df.columns:
        return [
            {
                "type": "partner_drift",
                "severity": "info",
                "column": None,
                "message": "Partner drift skipped: no partner-identifying column detected.",
                "metrics": {},
            }
        ]

    current_profile = build_partner_profile(current_df, partner_col=partner_col)
    if not current_profile:
        return [
            {
                "type": "partner_drift",
                "severity": "info",
                "column": partner_col,
                "message": "Partner drift skipped: insufficient partner values.",
                "metrics": {},
            }
        ]

    if baseline_profile:
        distance = _distribution_distance(current_profile, baseline_profile)
        if distance >= 0.25:
            anomalies.append(
                {
                    "type": "partner_drift",
                    "severity": "high" if distance >= 0.40 else "medium",
                    "column": partner_col,
                    "message": (
                        f"Partner distribution drift detected in '{partner_col}' "
                        f"(distance={distance:.3f} vs historical baseline)."
                    ),
                    "metrics": {
                        "distribution_distance": round(distance, 4),
                        "baseline_top": dict(list(baseline_profile.items())[:5]),
                        "current_top": dict(list(current_profile.items())[:5]),
                    },
                }
            )
        else:
            anomalies.append(
                {
                    "type": "partner_drift",
                    "severity": "info",
                    "column": partner_col,
                    "message": f"No material partner drift detected (distance={distance:.3f}).",
                    "metrics": {"distribution_distance": round(distance, 4)},
                }
            )
        return anomalies

    # No baseline available: compare first/second half for an early drift heuristic.
    if len(current_df) >= 20:
        halfway = len(current_df) // 2
        first_profile = build_partner_profile(current_df.iloc[:halfway], partner_col=partner_col)
        second_profile = build_partner_profile(current_df.iloc[halfway:], partner_col=partner_col)
        if first_profile and second_profile:
            distance = _distribution_distance(second_profile, first_profile)
            if distance >= 0.30:
                anomalies.append(
                    {
                        "type": "partner_drift",
                        "severity": "medium",
                        "column": partner_col,
                        "message": (
                            f"In-file partner drift signal detected in '{partner_col}' "
                            f"between first and second half (distance={distance:.3f})."
                        ),
                        "metrics": {"distribution_distance": round(distance, 4)},
                    }
                )
                return anomalies

    anomalies.append(
        {
            "type": "partner_drift",
            "severity": "info",
            "column": partner_col,
            "message": "Baseline history unavailable; partner drift cannot be robustly scored yet.",
            "metrics": {},
        }
    )
    return anomalies


def detect_anomalies(
    raw_df: pd.DataFrame,
    cleaned_df: Optional[pd.DataFrame] = None,
    baseline_partner_profile: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Detect anomalies and return grouped findings with summary counts."""
    findings: List[Dict[str, Any]] = []

    target_df = cleaned_df if cleaned_df is not None and not cleaned_df.empty else raw_df

    findings.extend(_distribution_anomalies(target_df))
    findings.extend(_null_spike_anomalies(raw_df, cleaned_df))
    findings.extend(_price_quantity_outlier_changes(raw_df, cleaned_df))
    findings.extend(
        _partner_drift_anomalies(
            target_df,
            baseline_profile=baseline_partner_profile,
            partner_col=detect_partner_column(target_df),
        )
    )

    high = len([f for f in findings if f.get("severity") == "high"])
    medium = len([f for f in findings if f.get("severity") == "medium"])
    info = len([f for f in findings if f.get("severity") == "info"])

    return {
        "summary": {
            "total_findings": len(findings),
            "high": high,
            "medium": medium,
            "info": info,
        },
        "findings": findings,
    }
