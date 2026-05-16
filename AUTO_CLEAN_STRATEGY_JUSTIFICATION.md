# Auto-Clean Strategy Justification (Phase 2)

## Purpose
This document explains how the platform selects the **first-run cleaning strategy automatically** after dataset upload, and why each strategy is chosen.

The objective of auto-clean is to provide a **safe, practical baseline clean** before user review. Users can still manually choose strategies and re-run cleaning afterward.

## Where This Logic Is Implemented
- Backend strategy resolver: `backend/app/routers/cleaning.py` (`_resolve_cleaning_strategies`)
- Cleaning operations engine: `backend/app/services/cleaning_engine.py`
- Frontend reflects applied strategy in Step 2 UI: `frontend/src/components/Dashboard/Dashboard.jsx`

## Auto-Selection Inputs
The resolver uses these dataset characteristics:
- Total rows
- Total columns
- Number of numeric columns
- Total missing cells
- Missing ratio = missing cells / total cells

## Missing-Value Strategy Rules (Auto Mode)
If `missing_strategy = auto`, the platform resolves to one of: `knn`, `median`, or `mean`.

### Rule 1
If total missing cells = 0 -> choose `mean`

Why:
- There is no actual imputation requirement.
- Keeps pipeline behavior consistent without introducing unnecessary transforms.

### Rule 2
If all conditions are true:
- numeric columns between 2 and 15
- row count <= 5000
- missing ratio <= 0.25

-> choose `knn`

Why:
- KNN can leverage multi-column numeric relationships and often preserves realistic structure better than univariate methods.
- Bounded row/feature limits keep runtime acceptable and reduce instability on very large datasets.

### Rule 3
Else if missing ratio >= 0.15 -> choose `median`

Why:
- Higher missingness increases risk of distortion.
- Median is robust to skew and extreme values compared with mean.

### Rule 4
Else -> choose `mean`

Why:
- For low-to-moderate missingness, mean is efficient and usually adequate.
- Helps keep first-pass cleaning fast.

## Outlier Strategy Rules (Auto Mode)
If `outlier_strategy = auto`, the platform resolves to one of: `iqr` or `none`.

### Rule 1
If there are no numeric columns -> choose `none`

Why:
- Statistical outlier treatment is not meaningful for non-numeric-only datasets.

### Rule 2
If numeric columns exist -> choose `iqr`

Why:
- IQR is non-parametric and robust across different numeric distributions.
- It is a safer first-pass default than distribution-sensitive assumptions.

## Why These Defaults Are Defensible
- **Safety first:** conservative and review-friendly choices for first run.
- **Practical performance:** avoids expensive methods for large/high-dimensional data.
- **Robustness:** prefers median and IQR in cases prone to skew/outliers.
- **Human-in-the-loop:** user approval is required before moving forward, and re-run with manual strategy remains available.

## Example Interpretation
For a dataset with:
- moderate missing values,
- several numeric columns,
- manageable size,

auto-clean will typically select:
- Missing strategy: `knn`
- Outlier strategy: `iqr`

For sparse numeric structure or very large data, it may fall back to:
- Missing strategy: `median` or `mean`
- Outlier strategy: `iqr` (or `none` if numeric columns absent)

## Known Limitation
Current resolver computes missing ratio before placeholder normalization in the cleaning engine.

Implication:
- Tokens like `/`, `NA`, `-`, etc. may be converted to missing values later, so the initial strategy decision may be slightly conservative in some datasets.

## Recommended Future Enhancement
Before resolving `auto`, run a lightweight pre-normalization pass for placeholder tokens on a temporary copy. Then compute missing ratio on normalized data. This will make auto-selection closer to true data quality conditions.

## Summary
The auto strategy is **rule-based, deterministic, and explainable**. It is designed for a reliable first-pass clean, followed by user review and optional manual re-run for fine-grained control.
