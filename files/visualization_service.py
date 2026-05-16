"""
StatsFlow Visualization Service
--------------------------------
Computes chart-ready data payloads from a cleaned DataFrame.

Chart Types Produced:
  - Histogram        : For each numeric column
  - Bar Chart        : For categorical columns (top 10 values)
  - Correlation Matrix: Heatmap-style data for numeric columns
  - Box Plot Data    : Quartile stats for numeric columns
  - Scatter Plot     : For the top 2 most correlated numeric column pair
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any
from app.utils.helpers import _convert_types


def generate_chart_data(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Generate all chart data payloads from a cleaned DataFrame.

    Args:
        df: The cleaned DataFrame.

    Returns:
        List of chart configuration dicts, each renderable by the frontend.
    """
    charts = []
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    categorical_cols = df.select_dtypes(
        include=["object", "category"]
    ).columns.tolist()

    # ── 1. Histograms for Numeric Columns ─────────────────────────────────────
    for col in numeric_cols[:6]:  # Limit to first 6 to avoid UI overload
        chart = _build_histogram(df, col)
        if chart:
            charts.append(chart)

    # ── 2. Bar Charts for Categorical Columns ─────────────────────────────────
    for col in categorical_cols[:4]:
        chart = _build_bar_chart(df, col)
        if chart:
            charts.append(chart)

    # ── 3. Correlation Heatmap ────────────────────────────────────────────────
    if len(numeric_cols) >= 2:
        chart = _build_correlation_matrix(df, numeric_cols)
        if chart:
            charts.append(chart)

    # ── 4. Box Plot Stats ─────────────────────────────────────────────────────
    if numeric_cols:
        chart = _build_boxplot_data(df, numeric_cols[:5])
        if chart:
            charts.append(chart)

    # ── 5. Scatter Plot (most correlated pair) ────────────────────────────────
    if len(numeric_cols) >= 2:
        chart = _build_scatter_plot(df, numeric_cols)
        if chart:
            charts.append(chart)

    return charts


def generate_recommended_charts(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Generate Excel-like recommended charts from dataset structure.

    Recommendations include:
      - Column chart (avg metric by top category)
      - Stacked column chart (top 2 metrics by category)
      - Line chart (metric over index/id-like sequence)
      - Pie chart (category share)
            - Area chart (smoothed trend)
            - Combo chart (bar + line)
            - Radar chart (multi-metric profile)
            - Treemap (hierarchical-like share)
            - Bubble chart (3-metric relationship)
    """
    recommendations: List[Dict[str, Any]] = []
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    categorical_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()

    if not numeric_cols:
        return recommendations

    primary_metric = next((c for c in numeric_cols if "id" not in c.lower()), numeric_cols[0])
    category_col = categorical_cols[0] if categorical_cols else None

    if category_col:
        col_chart = _build_recommended_column(df, category_col, primary_metric)
        if col_chart:
            recommendations.append(col_chart)

        stacked_chart = _build_recommended_stacked_column(df, category_col, numeric_cols)
        if stacked_chart:
            recommendations.append(stacked_chart)

        pie_chart = _build_recommended_pie(df, category_col)
        if pie_chart:
            recommendations.append(pie_chart)

        combo_chart = _build_recommended_combo(df, category_col, numeric_cols)
        if combo_chart:
            recommendations.append(combo_chart)

        radar_chart = _build_recommended_radar(df, category_col, numeric_cols)
        if radar_chart:
            recommendations.append(radar_chart)

        treemap_chart = _build_recommended_treemap(df, category_col)
        if treemap_chart:
            recommendations.append(treemap_chart)

    line_chart = _build_recommended_line(df, numeric_cols)
    if line_chart:
        recommendations.append(line_chart)

    area_chart = _build_recommended_area(df, numeric_cols)
    if area_chart:
        recommendations.append(area_chart)

    bubble_chart = _build_recommended_bubble(df, numeric_cols)
    if bubble_chart:
        recommendations.append(bubble_chart)

    return recommendations


def _build_histogram(df: pd.DataFrame, col: str) -> Dict[str, Any]:
    """Build histogram bin data for a single numeric column."""
    data = df[col].dropna()
    if data.empty:
        return None

    counts, bin_edges = np.histogram(data, bins=min(20, len(data.unique())))

    chart_data = [
        {
            "bin": f"{bin_edges[i]:.2f}–{bin_edges[i+1]:.2f}",
            "count": int(counts[i]),
            "range_start": float(bin_edges[i]),
            "range_end": float(bin_edges[i + 1]),
        }
        for i in range(len(counts))
    ]

    return {
        "id": f"hist_{col}",
        "type": "histogram",
        "title": f"Distribution of {col}",
        "column": col,
        "x_key": "bin",
        "y_key": "count",
        "data": chart_data,
        "stats": {
            "mean": round(float(data.mean()), 4),
            "median": round(float(data.median()), 4),
            "std": round(float(data.std()), 4),
            "min": round(float(data.min()), 4),
            "max": round(float(data.max()), 4),
        },
    }


def _build_bar_chart(df: pd.DataFrame, col: str) -> Dict[str, Any]:
    """Build bar chart data for a categorical column's value counts."""
    value_counts = df[col].value_counts().head(10)
    if value_counts.empty:
        return None

    chart_data = [
        {"category": str(k), "count": int(v)}
        for k, v in value_counts.items()
    ]

    return {
        "id": f"bar_{col}",
        "type": "bar",
        "title": f"Value Distribution: {col}",
        "column": col,
        "x_key": "category",
        "y_key": "count",
        "data": chart_data,
    }


def _build_correlation_matrix(
    df: pd.DataFrame, numeric_cols: List[str]
) -> Dict[str, Any]:
    """Build correlation matrix data for a heatmap visualization."""
    cols = numeric_cols[:8]  # Cap at 8 columns for readability
    corr_matrix = df[cols].corr()

    # Flatten the matrix into a list of {x, y, value} triplets for frontend
    heatmap_data = []
    for i, row_col in enumerate(cols):
        for j, col_col in enumerate(cols):
            val = corr_matrix.iloc[i, j]
            heatmap_data.append({
                "x": col_col,
                "y": row_col,
                "value": round(float(val), 3) if not np.isnan(val) else 0.0,
            })

    return {
        "id": "correlation_matrix",
        "type": "heatmap",
        "title": "Feature Correlation Matrix",
        "columns": cols,
        "data": heatmap_data,
    }


def _build_boxplot_data(
    df: pd.DataFrame, numeric_cols: List[str]
) -> Dict[str, Any]:
    """Build box plot statistics for multiple numeric columns."""
    boxplot_data = []

    for col in numeric_cols:
        data = df[col].dropna()
        if data.empty or len(data) < 4:
            continue

        q1 = float(data.quantile(0.25))
        q3 = float(data.quantile(0.75))
        iqr = q3 - q1

        boxplot_data.append({
            "column": col,
            "min": round(float(data.min()), 4),
            "q1": round(q1, 4),
            "median": round(float(data.median()), 4),
            "q3": round(q3, 4),
            "max": round(float(data.max()), 4),
            "iqr": round(iqr, 4),
            "mean": round(float(data.mean()), 4),
        })

    if not boxplot_data:
        return None

    return {
        "id": "boxplot",
        "type": "boxplot",
        "title": "Numeric Column Box Plots",
        "data": boxplot_data,
    }


def _build_scatter_plot(
    df: pd.DataFrame, numeric_cols: List[str]
) -> Dict[str, Any]:
    """
    Build a scatter plot for the most strongly correlated numeric column pair.
    Falls back to the first two numeric columns if correlation is unavailable.
    """
    if len(numeric_cols) < 2:
        return None

    # Find the pair with highest absolute correlation (excluding self-correlation)
    corr = df[numeric_cols].corr().abs()
    np.fill_diagonal(corr.values, 0)  # Exclude self-correlation

    max_val = corr.max().max()
    if max_val > 0:
        col_pair = corr.stack().idxmax()
        x_col, y_col = col_pair[0], col_pair[1]
    else:
        x_col, y_col = numeric_cols[0], numeric_cols[1]

    sample = df[[x_col, y_col]].dropna().head(300)  # Cap at 300 points

    chart_data = [
        {"x": float(row[x_col]), "y": float(row[y_col])}
        for _, row in sample.iterrows()
    ]

    return {
        "id": f"scatter_{x_col}_{y_col}",
        "type": "scatter",
        "title": f"Scatter: {x_col} vs {y_col}",
        "x_col": x_col,
        "y_col": y_col,
        "x_key": "x",
        "y_key": "y",
        "data": chart_data,
        "correlation": round(float(df[x_col].corr(df[y_col])), 4),
    }


def _build_recommended_column(df: pd.DataFrame, category_col: str, metric_col: str) -> Dict[str, Any]:
    grouped = (
        df[[category_col, metric_col]]
        .dropna()
        .groupby(category_col, as_index=False)[metric_col]
        .mean()
        .sort_values(metric_col, ascending=False)
        .head(10)
    )
    if grouped.empty:
        return None

    data = [
        {
            "category": str(row[category_col]),
            "value": round(float(row[metric_col]), 4),
        }
        for _, row in grouped.iterrows()
    ]

    return {
        "id": f"recommended_column_{category_col}_{metric_col}",
        "type": "column",
        "title": f"Recommended: Avg {metric_col} by {category_col}",
        "x_key": "category",
        "y_key": "value",
        "data": data,
        "recommendation_reason": "Shows category-level comparison using average metric values.",
    }


def _build_recommended_stacked_column(df: pd.DataFrame, category_col: str, numeric_cols: List[str]) -> Dict[str, Any]:
    metric_candidates = [c for c in numeric_cols if "id" not in c.lower()]
    if len(metric_candidates) < 2:
        return None

    metrics = metric_candidates[:2]
    grouped = df[[category_col] + metrics].dropna().groupby(category_col, as_index=False).mean()
    if grouped.empty:
        return None

    rows = []
    for _, row in grouped.iterrows():
        item = {"category": str(row[category_col])}
        for m in metrics:
            item[m] = round(float(row[m]), 4)
        rows.append(item)

    return {
        "id": f"recommended_stacked_{category_col}",
        "type": "stacked_column",
        "title": f"Recommended: {metrics[0]} + {metrics[1]} by {category_col}",
        "x_key": "category",
        "series": metrics,
        "data": rows,
        "recommendation_reason": "Combines two metrics in one stacked view to compare total contributions.",
    }


def _build_recommended_line(df: pd.DataFrame, numeric_cols: List[str]) -> Dict[str, Any]:
    metric_candidates = [c for c in numeric_cols if "id" not in c.lower()]
    metric = metric_candidates[0] if metric_candidates else numeric_cols[0]

    index_col = next((c for c in df.columns if "id" in c.lower()), None)
    if index_col and index_col in df.columns:
        temp = df[[index_col, metric]].dropna().sort_values(index_col).head(300)
        x_key = "x"
        data = [{"x": str(row[index_col]), "value": float(row[metric])} for _, row in temp.iterrows()]
        x_label = index_col
    else:
        temp = df[[metric]].dropna().reset_index(drop=True).head(300)
        x_key = "x"
        data = [{"x": int(idx + 1), "value": float(val)} for idx, val in enumerate(temp[metric].tolist())]
        x_label = "Row Index"

    if not data:
        return None

    return {
        "id": f"recommended_line_{metric}",
        "type": "line",
        "title": f"Recommended: {metric} Trend",
        "x_key": x_key,
        "y_key": "value",
        "x_label": x_label,
        "data": data,
        "recommendation_reason": "Best for trend/sequence patterns across rows or identifier order.",
    }


def _build_recommended_pie(df: pd.DataFrame, category_col: str) -> Dict[str, Any]:
    counts = df[category_col].dropna().astype(str).value_counts().head(8)
    if counts.empty:
        return None

    total = int(counts.sum())
    data = [
        {
            "name": str(k),
            "value": int(v),
            "pct": round((int(v) / total) * 100, 2) if total > 0 else 0.0,
        }
        for k, v in counts.items()
    ]

    return {
        "id": f"recommended_pie_{category_col}",
        "type": "pie",
        "title": f"Recommended: Share of {category_col}",
        "name_key": "name",
        "value_key": "value",
        "data": data,
        "recommendation_reason": "Shows category composition and dominant segments quickly.",
    }


def _build_recommended_area(df: pd.DataFrame, numeric_cols: List[str]) -> Dict[str, Any]:
    metric_candidates = [c for c in numeric_cols if "id" not in c.lower()]
    metric = metric_candidates[0] if metric_candidates else (numeric_cols[0] if numeric_cols else None)
    if not metric:
        return None

    index_col = next((c for c in df.columns if "id" in c.lower()), None)
    if index_col and index_col in df.columns:
        temp = df[[index_col, metric]].dropna().sort_values(index_col).head(240)
        data = [{"x": str(row[index_col]), "value": round(float(row[metric]), 4)} for _, row in temp.iterrows()]
        x_label = index_col
    else:
        temp = df[[metric]].dropna().reset_index(drop=True).head(240)
        data = [{"x": idx + 1, "value": round(float(val), 4)} for idx, val in enumerate(temp[metric].tolist())]
        x_label = "Row Index"

    if not data:
        return None

    return {
        "id": f"recommended_area_{metric}",
        "type": "area",
        "title": f"Recommended: {metric} Area Trend",
        "x_key": "x",
        "y_key": "value",
        "x_label": x_label,
        "data": data,
        "recommendation_reason": "Highlights cumulative trend and magnitude changes over sequence.",
    }


def _build_recommended_combo(df: pd.DataFrame, category_col: str, numeric_cols: List[str]) -> Dict[str, Any]:
    metric_candidates = [c for c in numeric_cols if "id" not in c.lower()]
    if len(metric_candidates) < 2:
        return None

    bar_metric, line_metric = metric_candidates[:2]
    grouped = (
        df[[category_col, bar_metric, line_metric]]
        .dropna()
        .groupby(category_col, as_index=False)
        .mean()
        .sort_values(bar_metric, ascending=False)
        .head(12)
    )
    if grouped.empty:
        return None

    data = []
    for _, row in grouped.iterrows():
        data.append({
            "category": str(row[category_col]),
            "bar_value": round(float(row[bar_metric]), 4),
            "line_value": round(float(row[line_metric]), 4),
        })

    return {
        "id": f"recommended_combo_{category_col}",
        "type": "combo",
        "title": f"Recommended: {bar_metric} + {line_metric} by {category_col}",
        "x_key": "category",
        "bar_key": "bar_value",
        "line_key": "line_value",
        "bar_label": bar_metric,
        "line_label": line_metric,
        "data": data,
        "recommendation_reason": "Compares two metrics together using bars and a trend line.",
    }


def _build_recommended_radar(df: pd.DataFrame, category_col: str, numeric_cols: List[str]) -> Dict[str, Any]:
    metric_candidates = [c for c in numeric_cols if "id" not in c.lower()][:5]
    if len(metric_candidates) < 3:
        return None

    top_category = (
        df[category_col].dropna().astype(str).value_counts().index.tolist()
    )
    if not top_category:
        return None

    selected = top_category[0]
    subset = df[df[category_col].astype(str) == selected]
    if subset.empty:
        return None

    data = []
    for metric in metric_candidates:
        values = subset[metric].dropna()
        if values.empty:
            continue
        data.append({
            "subject": metric,
            "value": round(float(values.mean()), 4),
        })

    if len(data) < 3:
        return None

    return {
        "id": f"recommended_radar_{category_col}",
        "type": "radar",
        "title": f"Recommended: Metric Profile for {selected}",
        "angle_key": "subject",
        "value_key": "value",
        "data": data,
        "recommendation_reason": "Useful for comparing multiple metrics in one compact profile.",
    }


def _build_recommended_treemap(df: pd.DataFrame, category_col: str) -> Dict[str, Any]:
    counts = df[category_col].dropna().astype(str).value_counts().head(12)
    if counts.empty:
        return None

    data = [{"name": str(k), "size": int(v)} for k, v in counts.items()]

    return {
        "id": f"recommended_treemap_{category_col}",
        "type": "treemap",
        "title": f"Recommended: {category_col} Treemap",
        "name_key": "name",
        "value_key": "size",
        "data": data,
        "recommendation_reason": "Best for spotting dominant segments in category-heavy data.",
    }


def _build_recommended_bubble(df: pd.DataFrame, numeric_cols: List[str]) -> Dict[str, Any]:
    metric_candidates = [c for c in numeric_cols if "id" not in c.lower()]
    cols = metric_candidates[:3] if len(metric_candidates) >= 3 else numeric_cols[:3]
    if len(cols) < 3:
        return None

    x_col, y_col, z_col = cols
    sample = df[[x_col, y_col, z_col]].dropna().head(220)
    if sample.empty:
        return None

    z_min = float(sample[z_col].min())
    z_max = float(sample[z_col].max())
    z_range = z_max - z_min if z_max != z_min else 1.0

    data = []
    for _, row in sample.iterrows():
        z_val = float(row[z_col])
        norm = (z_val - z_min) / z_range
        data.append({
            "x": round(float(row[x_col]), 4),
            "y": round(float(row[y_col]), 4),
            "z": round(z_val, 4),
            "size": round(8 + norm * 22, 2),
        })

    return {
        "id": f"recommended_bubble_{x_col}_{y_col}_{z_col}",
        "type": "bubble",
        "title": f"Recommended: {x_col} vs {y_col} (size: {z_col})",
        "x_key": "x",
        "y_key": "y",
        "z_key": "z",
        "size_key": "size",
        "x_label": x_col,
        "y_label": y_col,
        "size_label": z_col,
        "data": data,
        "recommendation_reason": "Reveals 3-metric relationships in one visual.",
    }