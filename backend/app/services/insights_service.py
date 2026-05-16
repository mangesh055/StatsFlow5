"""
StatsFlow Insights Service
---------------------------
Applies Simple Linear Regression (SLR) to numeric column pairs and generates
plain-English trend statements.

This simulates an "Auto-Generated Trend Highlights" feature, allowing
non-technical users to immediately understand relationships in their data.
"""

import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score
from typing import Dict, List, Any, Tuple


def generate_insights(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Generate statistical and trend-based insights from a cleaned DataFrame.

    Produces two categories:
    1. SLR-based trend insights for numeric column pairs
    2. Descriptive summary insights for all columns

    Args:
        df: The cleaned DataFrame.

    Returns:
        List of insight dicts, each containing type, title, and body text.
    """
    insights = []
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    categorical_cols = df.select_dtypes(
        include=["object", "category"]
    ).columns.tolist()

    # ── SLR Trend Insights ────────────────────────────────────────────────────
    # Evaluate top correlated pairs and produce regression-based insights
    if len(numeric_cols) >= 2:
        slr_insights = _generate_slr_insights(df, numeric_cols)
        insights.extend(slr_insights)

    # ── Distribution Insights ─────────────────────────────────────────────────
    for col in numeric_cols[:5]:
        insight = _generate_distribution_insight(df, col)
        if insight:
            insights.append(insight)

    # ── Categorical Dominance Insights ────────────────────────────────────────
    for col in categorical_cols[:3]:
        insight = _generate_categorical_insight(df, col)
        if insight:
            insights.append(insight)

    # ── Dataset-Level Summary ─────────────────────────────────────────────────
    insights.insert(0, _generate_dataset_summary(df, numeric_cols, categorical_cols))

    return insights


def _generate_slr_insights(
    df: pd.DataFrame, numeric_cols: List[str]
) -> List[Dict[str, Any]]:
    """
    For the top 3 most correlated numeric pairs, fit a Simple Linear Regression
    and generate a plain-English insight about the trend.
    """
    insights = []

    # Compute all pairwise correlations and sort by absolute value
    corr_pairs: List[Tuple[float, str, str]] = []
    corr_matrix = df[numeric_cols].corr()

    for i, col_a in enumerate(numeric_cols):
        for j, col_b in enumerate(numeric_cols):
            if j <= i:
                continue  # Avoid duplicates and self-correlation
            corr_val = corr_matrix.loc[col_a, col_b]
            if not np.isnan(corr_val):
                corr_pairs.append((abs(corr_val), col_a, col_b))

    # Sort descending by correlation strength and take top 3
    corr_pairs.sort(reverse=True)
    top_pairs = corr_pairs[:3]

    for abs_corr, col_x, col_y in top_pairs:
        insight = _fit_slr_and_describe(df, col_x, col_y, abs_corr)
        if insight:
            insights.append(insight)

    return insights


def _fit_slr_and_describe(
    df: pd.DataFrame,
    col_x: str,
    col_y: str,
    abs_corr: float,
) -> Dict[str, Any]:
    """
    Fit a Simple Linear Regression model between two columns and
    produce a plain-English trend statement.

    Args:
        df: Source DataFrame.
        col_x: Independent variable column name.
        col_y: Dependent variable column name.
        abs_corr: Pre-computed absolute Pearson correlation.

    Returns:
        Insight dict or None if not enough data.
    """
    sample = df[[col_x, col_y]].dropna()
    if len(sample) < 5:
        return None

    X = sample[[col_x]].values
    y = sample[col_y].values

    # Fit the regression model
    model = LinearRegression()
    model.fit(X, y)
    y_pred = model.predict(X)

    r2 = r2_score(y, y_pred)
    slope = model.coef_[0]
    intercept = model.intercept_

    # Determine direction and strength of the relationship
    direction = "increases" if slope > 0 else "decreases"
    strength = _get_correlation_strength(abs_corr)
    sign = "+" if slope > 0 else ""

    # Compute a meaningful "when X exceeds..." threshold
    x_mean = float(sample[col_x].mean())
    x_75th = float(sample[col_x].quantile(0.75))

    # Generate the insight statement
    body = (
        f"A {strength} {direction[:-1]}ing relationship was detected between "
        f"'{col_x}' and '{col_y}' (correlation: {abs_corr:.2f}, R²: {r2:.3f}). "
        f"For every 1-unit increase in '{col_x}', '{col_y}' tends to "
        f"{direction[:-1]} by approximately {abs(slope):.4f} units "
        f"(slope: {sign}{slope:.4f}, intercept: {intercept:.4f}). "
        f"When '{col_x}' exceeds {x_75th:.2f} (75th percentile), "
        f"'{col_y}' is predicted to be around "
        f"{model.predict([[x_75th]])[0]:.2f}."
    )

    return {
        "id": f"slr_{col_x}_{col_y}",
        "type": "trend",
        "icon": "📈" if slope > 0 else "📉",
        "title": f"Trend: {col_x} → {col_y}",
        "body": body,
        "stats": {
            "slope": round(float(slope), 6),
            "intercept": round(float(intercept), 6),
            "r_squared": round(float(r2), 4),
            "correlation": round(float(abs_corr), 4),
            "x_mean": round(x_mean, 4),
        },
        "x_col": col_x,
        "y_col": col_y,
    }


def _generate_distribution_insight(
    df: pd.DataFrame, col: str
) -> Dict[str, Any]:
    """Generate a descriptive insight about the distribution of a numeric column."""
    data = df[col].dropna()
    if data.empty:
        return None

    mean_val = data.mean()
    median_val = data.median()
    std_val = data.std()

    # Detect skewness
    skewness = data.skew()
    if skewness > 1:
        skew_desc = "strongly right-skewed (positively skewed)"
    elif skewness > 0.5:
        skew_desc = "moderately right-skewed"
    elif skewness < -1:
        skew_desc = "strongly left-skewed (negatively skewed)"
    elif skewness < -0.5:
        skew_desc = "moderately left-skewed"
    else:
        skew_desc = "approximately symmetric (near-normal distribution)"

    body = (
        f"'{col}' ranges from {data.min():.2f} to {data.max():.2f} with a mean of "
        f"{mean_val:.2f} and median of {median_val:.2f} (std: {std_val:.2f}). "
        f"The distribution is {skew_desc} (skewness: {skewness:.2f}). "
    )

    if abs(mean_val - median_val) > 0.1 * std_val and std_val > 0:
        body += (
            f"The gap between mean and median suggests the presence of extreme values "
            f"that may be influencing the average."
        )

    return {
        "id": f"dist_{col}",
        "type": "distribution",
        "icon": "📊",
        "title": f"Distribution: {col}",
        "body": body,
        "stats": {
            "mean": round(float(mean_val), 4),
            "median": round(float(median_val), 4),
            "std": round(float(std_val), 4),
            "skewness": round(float(skewness), 4),
        },
    }


def _generate_categorical_insight(
    df: pd.DataFrame, col: str
) -> Dict[str, Any]:
    """Generate an insight about the dominant categories in a categorical column."""
    value_counts = df[col].value_counts()
    if value_counts.empty:
        return None

    top_category = str(value_counts.index[0])
    top_count = int(value_counts.iloc[0])
    top_pct = round(top_count / len(df) * 100, 1)
    unique_count = int(df[col].nunique())

    body = (
        f"'{col}' has {unique_count} unique value(s). "
        f"The most frequent category is '{top_category}', "
        f"appearing in {top_count} rows ({top_pct}% of the dataset). "
    )

    if unique_count == 2:
        body += "This is a binary categorical feature."
    elif unique_count > 20:
        body += "High cardinality — consider encoding or grouping rare categories."

    return {
        "id": f"cat_{col}",
        "type": "categorical",
        "icon": "🏷️",
        "title": f"Category Profile: {col}",
        "body": body,
        "stats": {
            "unique_values": unique_count,
            "top_category": top_category,
            "top_frequency_pct": top_pct,
        },
    }


def _generate_dataset_summary(
    df: pd.DataFrame,
    numeric_cols: List[str],
    categorical_cols: List[str],
) -> Dict[str, Any]:
    """Generate a high-level dataset summary insight."""
    missing_count = int(df.isnull().sum().sum())
    missing_pct = round(missing_count / (df.shape[0] * df.shape[1]) * 100, 2)

    body = (
        f"The cleaned dataset contains {df.shape[0]:,} rows and {df.shape[1]} columns "
        f"({len(numeric_cols)} numeric, {len(categorical_cols)} categorical). "
        f"After cleaning, {missing_pct}% of cells contain missing values "
        f"({missing_count} total missing cells). "
    )

    if missing_pct == 0:
        body += "The dataset is fully complete with no missing values."
    elif missing_pct < 5:
        body += "Minimal missing data remains — the dataset is high quality."

    return {
        "id": "dataset_summary",
        "type": "summary",
        "icon": "🗂️",
        "title": "Dataset Overview",
        "body": body,
        "stats": {
            "rows": df.shape[0],
            "columns": df.shape[1],
            "numeric_columns": len(numeric_cols),
            "categorical_columns": len(categorical_cols),
            "missing_pct": missing_pct,
        },
    }


def _get_correlation_strength(abs_corr: float) -> str:
    """Map absolute correlation value to a descriptive strength label."""
    if abs_corr >= 0.8:
        return "very strong"
    elif abs_corr >= 0.6:
        return "strong"
    elif abs_corr >= 0.4:
        return "moderate"
    elif abs_corr >= 0.2:
        return "weak"
    else:
        return "very weak"