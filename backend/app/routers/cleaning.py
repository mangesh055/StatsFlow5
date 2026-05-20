"""
StatsFlow Cleaning Router
--------------------------
Handles Phase 2: Automated data cleaning with human-in-the-loop review.
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse, FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db, get_mongo_db
from app.models.postgres_models import DataSession
from app.services.cleaning_engine import CleaningEngine, MISSING_PLACEHOLDER_TOKENS
from app.services.health_score import compute_health_score, get_score_label
from app.services.quality_scorecard import compute_quality_scorecard
from app.services.anomaly_detection import detect_anomalies, build_partner_profile
from app.services.pipeline_generator import generate_pipeline_script
from app.utils.helpers import df_to_json_safe, get_column_types, _convert_types
import logging

router = APIRouter(prefix="/api", tags=["Cleaning"])
logger = logging.getLogger(__name__)

ROW_ID_COL = "__sf_row_id"


class CleaningRequest(BaseModel):
    """Request body for the cleaning endpoint."""

    missing_strategy: Literal["auto", "mean", "median", "mode", "knn", "drop", "ai_impute"] = Field(
        default="auto",
        description="Strategy for handling missing values",
    )
    outlier_strategy: Literal["auto", "zscore", "iqr", "none"] = Field(
        default="auto",
        description="Strategy for treating outliers",
    )


class CellEditRequest(BaseModel):
    """Request body for updating a single cleaned-table cell."""

    row_index: int = Field(..., ge=0, description="Zero-based row index in cleaned dataset")
    column: str = Field(..., min_length=1, description="Column name to edit")
    value: Any = Field(default=None, description="New value for the target cell")


class FeedbackItem(BaseModel):
    """Single review decision for a specific change."""

    change_id: str = Field(..., min_length=1)
    action: Literal["keep", "revert", "edit"]
    manual_value: Optional[Any] = None


class FeedbackRequest(BaseModel):
    """User review payload for a cleaned session."""

    approval_status: Literal["approved", "needs_changes", "rerun"]
    trust_score: Optional[int] = Field(default=None, ge=1, le=5)
    comments: Optional[str] = None
    strategy_feedback: Optional[Dict[str, Any]] = None
    per_change_actions: List[FeedbackItem] = Field(default_factory=list)


class RevertChangesRequest(BaseModel):
    """Request body for reverting selected cell-level changes."""

    change_ids: List[str] = Field(default_factory=list, min_length=1)


class FinalizeRequest(BaseModel):
    """Finalize request with optional summary comment."""

    notes: Optional[str] = None


class FeatureEngineeringApplyRequest(BaseModel):
    """Apply selected AI-suggested features to the cleaned dataset."""
    selected_features: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of validated feature specs to apply"
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _values_equal(a: Any, b: Any) -> bool:
    """Compare values with NaN/None awareness and numeric tolerance."""
    if pd.isna(a) and pd.isna(b):
        return True

    if isinstance(a, (int, float, np.number)) and isinstance(b, (int, float, np.number)):
        try:
            return bool(np.isclose(float(a), float(b), rtol=1e-9, atol=1e-12, equal_nan=True))
        except Exception:
            return str(a) == str(b)

    return str(a) == str(b)


def _safe_json_value(value: Any) -> Any:
    """Convert values into JSON-safe Python primitives."""
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        as_float = float(value)
        if np.isnan(as_float) or np.isinf(as_float):
            return None
        return as_float
    if pd.isna(value):
        return None
    return value


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively convert dicts, lists, and values into JSON-safe primitives."""
    if isinstance(obj, dict):
        return {str(k): _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, tuple):
        return [_sanitize_for_json(v) for v in obj]
    return _safe_json_value(obj)


def _is_missing_like(value: Any) -> bool:
    if value is None or pd.isna(value):
        return True
    if isinstance(value, str):
        return value.strip().lower() in MISSING_PLACEHOLDER_TOKENS
    return False


def _confidence_for_reason(reason_tag: str) -> float:
    confidence = {
        "missing_imputed": 0.92,
        "outlier_adjusted": 0.78,
        "value_adjusted": 0.74,
        "value_updated": 0.65,
        "row_removed": 0.70,
        "column_dropped": 0.82,
        "manual_edit": 1.00,
    }
    return confidence.get(reason_tag, 0.60)


def _confidence_label(score: float) -> str:
    if score >= 0.90:
        return "high"
    if score >= 0.75:
        return "medium"
    return "low"


def _reason_for_cell_change(before: Any, after: Any) -> str:
    if _is_missing_like(before) and not _is_missing_like(after):
        return "missing_imputed"

    numeric_before = isinstance(before, (int, float, np.number)) and not pd.isna(before)
    numeric_after = isinstance(after, (int, float, np.number)) and not pd.isna(after)
    if numeric_before and numeric_after:
        before_f = float(before)
        after_f = float(after)
        if before_f != 0 and abs(after_f - before_f) / abs(before_f) < 0.35:
            return "outlier_adjusted"
        return "value_adjusted"

    return "value_updated"


def _explainability_for_change(column: str, before: Any, after: Any, reason_tag: str) -> str:
    if reason_tag == "missing_imputed":
        return (
            f"Column '{column}' had a missing placeholder and was imputed to improve completeness "
            f"(before={before}, after={after})."
        )
    if reason_tag == "outlier_adjusted":
        return (
            f"Column '{column}' looked like an outlier and was adjusted within expected range "
            f"(before={before}, after={after})."
        )
    if reason_tag == "value_adjusted":
        return (
            f"Numeric value in '{column}' was transformed by cleaning rules "
            f"(before={before}, after={after})."
        )
    if reason_tag == "manual_edit":
        return f"Manual user edit applied to '{column}' (before={before}, after={after})."
    return f"Value in '{column}' changed by cleaning logic (before={before}, after={after})."


def _coerce_value_for_column(series: pd.Series, value: Any) -> Any:
    """Coerce incoming edited value to match DataFrame column dtype where possible."""
    if value is None:
        return None

    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return None
        value = stripped

    if pd.api.types.is_numeric_dtype(series):
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError(f"Value '{value}' is not a valid number for column '{series.name}'.")

    if pd.api.types.is_datetime64_any_dtype(series):
        try:
            return pd.to_datetime(value)
        except Exception:
            raise ValueError(f"Value '{value}' is not a valid datetime for column '{series.name}'.")

    return str(value)


def _public_df(df_with_row_id: pd.DataFrame) -> pd.DataFrame:
    return df_with_row_id.drop(columns=[ROW_ID_COL], errors="ignore")


def _ensure_row_id(df: pd.DataFrame) -> pd.DataFrame:
    if ROW_ID_COL not in df.columns:
        df = df.copy()
        df.insert(0, ROW_ID_COL, np.arange(len(df), dtype=int))
    return df


def _get_or_create_working_copy(session: DataSession) -> Tuple[str, pd.DataFrame]:
    """
    Get or create the working copy file for chatbot edits.
    The working copy is a copy of the cleaned file that can be edited without 
    affecting the original cleaned data.
    
    Returns:
        Tuple of (working_file_path, working_dataframe)
    """
    if session.chatbot_working_file_path and os.path.exists(session.chatbot_working_file_path):
        try:
            working_df = pd.read_csv(session.chatbot_working_file_path, low_memory=False)
            return session.chatbot_working_file_path, working_df
        except Exception:
            pass
    
    # Create a new working copy from the cleaned file
    if not session.cleaned_file_path or not os.path.exists(session.cleaned_file_path):
        raise HTTPException(status_code=404, detail="Cleaned dataset not found. Run cleaning first.")
    
    try:
        cleaned_df = pd.read_csv(session.cleaned_file_path, low_memory=False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load cleaned data: {str(exc)}")
    
    # Create working copy path
    working_path = os.path.join(settings.upload_dir, f"{session.session_id}_chatbot_working.csv")
    cleaned_df.to_csv(working_path, index=False)
    
    from app.services.cloud_storage import sync_to_cloud
    sync_to_cloud(working_path)
    
    # Save the path in the database
    session.chatbot_working_file_path = working_path
    
    return working_path, cleaned_df


def _load_raw_with_row_id(session: DataSession) -> pd.DataFrame:
    if not session.file_path or not os.path.exists(session.file_path):
        raise HTTPException(status_code=404, detail="Raw data file not found on disk.")
    try:
        raw_df = pd.read_csv(session.file_path, low_memory=False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load raw data: {str(exc)}")
    return _ensure_row_id(raw_df)


def _load_cleaned_with_row_id(session: DataSession) -> pd.DataFrame:
    if not session.cleaned_file_path or not os.path.exists(session.cleaned_file_path):
        raise HTTPException(status_code=404, detail="Cleaned dataset not found. Run cleaning first.")
    try:
        cleaned_df = pd.read_csv(session.cleaned_file_path, low_memory=False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load cleaned data: {str(exc)}")
    return _ensure_row_id(cleaned_df)


def _columns_info(df: pd.DataFrame) -> List[Dict[str, Any]]:
    column_types = get_column_types(df)
    info: List[Dict[str, Any]] = []
    for col in df.columns:
        missing_pct = round(float(df[col].isnull().mean() * 100), 2)
        info.append(
            {
                "name": col,
                "type": column_types[col],
                "dtype": str(df[col].dtype),
                "missing_count": int(df[col].isnull().sum()),
                "missing_pct": missing_pct,
                "unique_count": int(df[col].nunique()),
            }
        )
    return info


def _session_metrics_payload(session: DataSession, cleaned_df: pd.DataFrame) -> Dict[str, Any]:
    health = compute_health_score(cleaned_df)
    quality = compute_quality_scorecard(cleaned_df)
    return {
        "shape": {
            "rows": int(cleaned_df.shape[0]),
            "columns": int(cleaned_df.shape[1]),
        },
        "health": {
            **health,
            "label": get_score_label(health["total"]),
        },
        "raw_health": {
            "total": session.raw_health_score,
            "label": get_score_label(session.raw_health_score),
        },
        "quality_scorecard": quality,
    }


async def _build_feed_baseline_partner_profile(
    db: AsyncSession,
    current_session: DataSession,
    max_sessions: int = 3,
) -> Optional[Dict[str, float]]:
    stmt = (
        select(DataSession)
        .where(
            DataSession.filename == current_session.filename,
            DataSession.session_id != current_session.session_id,
        )
        .order_by(desc(DataSession.created_at))
        .limit(max_sessions)
    )
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    for prev in sessions:
        candidate_path = prev.approved_file_path or prev.cleaned_file_path or prev.file_path
        if not candidate_path or not os.path.exists(candidate_path):
            continue
        try:
            prev_df = pd.read_csv(candidate_path, low_memory=False)
        except Exception:
            continue

        profile = build_partner_profile(prev_df)
        if profile:
            return profile

    return None


def _resolve_cleaning_strategies(
    raw_with_row_id: pd.DataFrame,
    missing_strategy: str,
    outlier_strategy: str,
) -> Tuple[str, str]:
    """Resolve 'auto' strategies into concrete missing/outlier methods."""
    raw_df = _public_df(raw_with_row_id)
    numeric_df = raw_df.select_dtypes(include=[np.number])
    numeric_cols = list(numeric_df.columns)

    total_cells = int(raw_df.shape[0] * raw_df.shape[1]) if raw_df.shape[0] and raw_df.shape[1] else 0
    total_missing = int(raw_df.isnull().sum().sum()) if total_cells else 0
    missing_ratio = (total_missing / total_cells) if total_cells else 0.0

    missing_resolved = missing_strategy
    if missing_strategy == "auto":
        # Prefer robust imputation by default; use KNN when numeric structure is rich but still tractable.
        if total_missing == 0:
            missing_resolved = "mean"
        elif 2 <= len(numeric_cols) <= 15 and raw_df.shape[0] <= 5000 and missing_ratio <= 0.25:
            missing_resolved = "knn"
        elif missing_ratio >= 0.15:
            missing_resolved = "median"
        else:
            missing_resolved = "mean"

    outlier_resolved = outlier_strategy
    if outlier_strategy == "auto":
        if not numeric_cols:
            outlier_resolved = "none"
        else:
            outlier_resolved = "iqr"

    return missing_resolved, outlier_resolved


def _build_change_bundle(
    raw_with_row_id: pd.DataFrame,
    cleaned_with_row_id: pd.DataFrame,
    cleaning_report: Dict[str, Any],
    max_preview_rows: int = 50,
    max_change_log_entries: int = 5000,
) -> Dict[str, Any]:
    raw_indexed = raw_with_row_id.set_index(ROW_ID_COL, drop=False)
    cleaned_indexed = cleaned_with_row_id.set_index(ROW_ID_COL, drop=False)

    comparable_cols = [
        col for col in cleaned_with_row_id.columns if col in raw_with_row_id.columns and col != ROW_ID_COL
    ]

    modified_cells: List[Dict[str, Any]] = []
    change_log: List[Dict[str, Any]] = []

    preview_df = cleaned_with_row_id.head(max_preview_rows)
    row_id_to_preview_idx = {
        int(row[ROW_ID_COL]): idx for idx, (_, row) in enumerate(preview_df.iterrows())
    }

    for row_idx, (_, cleaned_row) in enumerate(cleaned_with_row_id.iterrows()):
        row_id = int(cleaned_row.get(ROW_ID_COL))
        if row_id not in raw_indexed.index:
            continue

        raw_row = raw_indexed.loc[row_id]
        for col in comparable_cols:
            before = raw_row[col]
            after = cleaned_row[col]
            if _values_equal(before, after):
                continue

            reason_tag = _reason_for_cell_change(before, after)
            confidence = _confidence_for_reason(reason_tag)
            change_id = f"cell:{row_id}:{col}"
            entry = {
                "change_id": change_id,
                "change_type": "cell_modified",
                "row": int(row_idx),
                "source_row_id": row_id,
                "column": col,
                "before": _safe_json_value(before),
                "after": _safe_json_value(after),
                "reason_tag": reason_tag,
                "reason": reason_tag.replace("_", " "),
                "confidence": confidence,
                "confidence_label": _confidence_label(confidence),
                "explanation": _explainability_for_change(
                    col,
                    _safe_json_value(before),
                    _safe_json_value(after),
                    reason_tag,
                ),
                "decision": "pending",
            }
            if len(change_log) < max_change_log_entries:
                change_log.append(entry)

            if row_id in row_id_to_preview_idx:
                modified_cells.append(
                    {
                        "change_id": change_id,
                        "row": int(row_id_to_preview_idx[row_id]),
                        "column": col,
                        "before": _safe_json_value(before),
                        "after": _safe_json_value(after),
                        "change_type": "auto_cleaned",
                        "reason_tag": reason_tag,
                        "confidence": confidence,
                        "confidence_label": _confidence_label(confidence),
                        "explanation": _explainability_for_change(
                            col,
                            _safe_json_value(before),
                            _safe_json_value(after),
                            reason_tag,
                        ),
                    }
                )

    raw_row_ids = set(raw_with_row_id[ROW_ID_COL].astype(int).tolist())
    cleaned_row_ids = set(cleaned_with_row_id[ROW_ID_COL].astype(int).tolist())
    removed_row_ids = sorted(raw_row_ids - cleaned_row_ids)

    for row_id in removed_row_ids:
        if len(change_log) >= max_change_log_entries:
            break
        change_log.append(
            {
                "change_id": f"row_removed:{row_id}",
                "change_type": "row_removed",
                "row": None,
                "source_row_id": int(row_id),
                "column": None,
                "before": "present",
                "after": "removed",
                "reason_tag": "row_removed",
                "reason": "row removed",
                "confidence": _confidence_for_reason("row_removed"),
                "confidence_label": _confidence_label(_confidence_for_reason("row_removed")),
                "explanation": "Row was removed because it violated cleaning rules (duplicates/null policy).",
                "decision": "pending",
            }
        )

    dropped_cols = cleaning_report.get("total_cols_removed", 0)
    if dropped_cols:
        cleaned_cols = set(cleaned_with_row_id.columns.tolist())
        raw_cols = [c for c in raw_with_row_id.columns.tolist() if c != ROW_ID_COL]
        dropped_col_names = [c for c in raw_cols if c not in cleaned_cols]
        for col in dropped_col_names:
            if len(change_log) >= max_change_log_entries:
                break
            change_log.append(
                {
                    "change_id": f"column_dropped:{col}",
                    "change_type": "column_dropped",
                    "row": None,
                    "source_row_id": None,
                    "column": col,
                    "before": "present",
                    "after": "dropped",
                    "reason_tag": "column_dropped",
                    "reason": "column dropped due to high missingness",
                    "confidence": _confidence_for_reason("column_dropped"),
                    "confidence_label": _confidence_label(_confidence_for_reason("column_dropped")),
                    "explanation": "Column exceeded missingness threshold and was removed to protect data quality.",
                    "decision": "pending",
                }
            )

    summary = {
        "total_changes": len(change_log),
        "modified_cells": len([c for c in change_log if c["change_type"] == "cell_modified"]),
        "rows_removed": len([c for c in change_log if c["change_type"] == "row_removed"]),
        "columns_dropped": len([c for c in change_log if c["change_type"] == "column_dropped"]),
        "imputed_cells": len([c for c in change_log if c.get("reason_tag") == "missing_imputed"]),
        "outlier_adjusted_cells": len(
            [c for c in change_log if c.get("reason_tag") in {"outlier_adjusted", "value_adjusted"}]
        ),
        "low_confidence_changes": len([c for c in change_log if float(c.get("confidence", 0.0)) < 0.75]),
    }

    return {
        "modified_cells": modified_cells,
        "change_log": change_log,
        "summary": summary,
    }


def _default_review_summary(
    cleaning_report: Dict[str, Any],
    change_bundle: Dict[str, Any],
    cleaned_health_total: float,
) -> Dict[str, Any]:
    return {
        "workflow_state": "under_review",
        "version": 1,
        "change_summary": change_bundle["summary"],
        "changes": change_bundle["change_log"],
        "decisions": {},
        "feedback_history": [],
        "strategy_feedback": [],
        "cleaned_health_score": cleaned_health_total,
        "cleaning_steps": cleaning_report.get("steps", []),
        "quality_scorecard": None,
        "anomaly_report": None,
        "approval_guardrails": {},
        "created_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
    }


def _merge_decisions_into_changes(changes: List[Dict[str, Any]], decisions: Dict[str, str]) -> List[Dict[str, Any]]:
    out = []
    for change in changes:
        copy_item = dict(change)
        decision = decisions.get(change.get("change_id", ""))
        if decision:
            copy_item["decision"] = decision
        out.append(copy_item)
    return out


def _set_status_for_feedback(current: str, approval_status: str) -> str:
    if approval_status == "approved":
        return "approved"
    if approval_status == "needs_changes":
        return "revised"
    if approval_status == "rerun":
        return current if current in {"under_review", "revised"} else "under_review"
    return current


def _build_review_response(
    session: DataSession,
    raw_with_row_id: pd.DataFrame,
    cleaned_with_row_id: pd.DataFrame,
) -> Dict[str, Any]:
    cleaned_public_df = _public_df(cleaned_with_row_id)
    review_summary = session.review_summary or {}
    decisions = review_summary.get("decisions", {})
    changes = review_summary.get("changes", [])

    return {
        "success": True,
        "session_id": session.session_id,
        "status": session.status,
        "workflow_state": review_summary.get("workflow_state", session.status),
        "cleaned_shape": {
            "rows": int(cleaned_public_df.shape[0]),
            "columns": int(cleaned_public_df.shape[1]),
        },
        "raw_health_score": {
            "total": session.raw_health_score,
            "label": get_score_label(session.raw_health_score),
        },
        "cleaned_health_score": {
            **compute_health_score(cleaned_public_df),
            "label": get_score_label(session.cleaned_health_score or 0),
        },
        "quality_scorecard": review_summary.get("quality_scorecard", {}),
        "anomaly_report": review_summary.get("anomaly_report", {}),
        "approval_guardrails": review_summary.get("approval_guardrails", {}),
        "cleaning_report": session.cleaning_summary,
        "review_summary": {
            **review_summary,
            "changes": _merge_decisions_into_changes(changes, decisions),
        },
        "raw_preview": df_to_json_safe(_public_df(raw_with_row_id), max_rows=500),
        "cleaned_preview": df_to_json_safe(cleaned_public_df, max_rows=500),
        "modified_cells": review_summary.get("modified_cells", []),
        "change_log": _merge_decisions_into_changes(changes, decisions),
        "change_summary": review_summary.get("change_summary", {}),
        "columns_info": _columns_info(cleaned_public_df),
    }


@router.post("/clean/{session_id}", summary="Run the automated cleaning pipeline")
async def clean_dataset(
    session_id: str,
    request: CleaningRequest,
    db: AsyncSession = Depends(get_db),
    mongo_db=Depends(get_mongo_db),
):
    result = await db.execute(select(DataSession).where(DataSession.session_id == session_id))
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    raw_with_row_id = _load_raw_with_row_id(session)

    resolved_missing_strategy, resolved_outlier_strategy = _resolve_cleaning_strategies(
        raw_with_row_id=raw_with_row_id,
        missing_strategy=request.missing_strategy,
        outlier_strategy=request.outlier_strategy,
    )

    if resolved_missing_strategy == "ai_impute":
        from app.services.ai_imputer import impute_missing_with_ai
        # Step 1: Normalize placeholder strings ("-", "NA", "/", etc.) → real NaN
        # so that pandas .isnull() correctly detects them for AI imputation.
        _pre_engine = CleaningEngine(raw_with_row_id)
        _pre_engine._normalize_placeholder_missing_values()
        normalized_df = _pre_engine.df  # df with real NaN where placeholders were

        # Step 2: AI imputation on the normalized dataframe
        ai_imputed_df = await impute_missing_with_ai(normalized_df)

        # Step 3: Pass AI-imputed df as the "raw" baseline for the main engine
        # The engine will skip imputation (strategy == 'ai_impute') and only do
        # duplicate removal, high-null column drops, outlier treatment, etc.
        engine = CleaningEngine(ai_imputed_df)
    else:
        engine = CleaningEngine(raw_with_row_id)

    cleaned_with_row_id, cleaning_report, operations = engine.clean(
        missing_strategy=resolved_missing_strategy,
        outlier_strategy=resolved_outlier_strategy,
    )
    cleaning_report = _sanitize_for_json(cleaning_report)

    cleaned_public_df = _public_df(cleaned_with_row_id)
    cleaned_health = compute_health_score(cleaned_public_df)
    cleaned_quality = compute_quality_scorecard(cleaned_public_df)
    raw_quality = compute_quality_scorecard(_public_df(raw_with_row_id))

    baseline_partner_profile = await _build_feed_baseline_partner_profile(db=db, current_session=session)
    anomaly_report = detect_anomalies(
        raw_df=_public_df(raw_with_row_id),
        cleaned_df=cleaned_public_df,
        baseline_partner_profile=baseline_partner_profile,
    )
    anomaly_report = _sanitize_for_json(anomaly_report)

    pipeline_script = generate_pipeline_script(
        filename=session.filename,
        operations=operations,
        missing_strategy=resolved_missing_strategy,
        outlier_strategy=resolved_outlier_strategy,
    )

    cleaned_path = os.path.join(settings.upload_dir, f"{session_id}_cleaned.csv")
    cleaned_with_row_id.to_csv(cleaned_path, index=False)
    from app.services.cloud_storage import sync_to_cloud
    sync_to_cloud(cleaned_path)

    change_bundle = _build_change_bundle(
        raw_with_row_id=raw_with_row_id,
        cleaned_with_row_id=cleaned_with_row_id,
        cleaning_report=cleaning_report,
    )
    change_bundle = _sanitize_for_json(change_bundle)
    review_summary = _default_review_summary(
        cleaning_report=cleaning_report,
        change_bundle=change_bundle,
        cleaned_health_total=cleaned_health["total"],
    )
    review_summary["modified_cells"] = change_bundle["modified_cells"]
    review_summary["quality_scorecard"] = {
        "raw": raw_quality,
        "cleaned": cleaned_quality,
    }
    review_summary["anomaly_report"] = anomaly_report
    review_summary["approval_guardrails"] = {
        "low_confidence_changes": change_bundle["summary"].get("low_confidence_changes", 0),
        "needs_human_review": change_bundle["summary"].get("low_confidence_changes", 0) > 0,
    }
    review_summary = _sanitize_for_json(review_summary)

    session.cleaned_file_path = cleaned_path
    session.approved_file_path = None
    session.cleaned_rows = int(cleaned_public_df.shape[0])
    session.cleaned_cols = int(cleaned_public_df.shape[1])
    session.cleaned_health_score = cleaned_health["total"]
    session.missing_strategy = resolved_missing_strategy
    session.outlier_strategy = resolved_outlier_strategy
    session.cleaning_summary = cleaning_report
    session.review_summary = review_summary
    session.status = "under_review"
    await db.flush()

    if mongo_db is not None:
        await mongo_db.processing_logs.insert_one(
            {
                "session_id": session_id,
                "event": "cleaning",
                "requested_missing_strategy": request.missing_strategy,
                "requested_outlier_strategy": request.outlier_strategy,
                "missing_strategy": resolved_missing_strategy,
                "outlier_strategy": resolved_outlier_strategy,
                "raw_health_score": session.raw_health_score,
                "cleaned_health_score": cleaned_health["total"],
                "operations": operations,
                "change_summary": change_bundle["summary"],
                "anomaly_summary": anomaly_report.get("summary", {}),
            }
        )

    logger.info(
        "Session %s cleaned (%sx%s), health=%s, review changes=%s",
        session_id,
        cleaned_public_df.shape[0],
        cleaned_public_df.shape[1],
        cleaned_health["total"],
        change_bundle["summary"].get("total_changes", 0),
    )

    return JSONResponse(
        content=_convert_types({
            "success": True,
            "session_id": session_id,
            "status": session.status,
            "workflow_state": "under_review",
            "cleaned_shape": {
                "rows": int(cleaned_public_df.shape[0]),
                "columns": int(cleaned_public_df.shape[1]),
            },
            "raw_health_score": {
                "total": session.raw_health_score,
                "label": get_score_label(session.raw_health_score),
            },
            "cleaned_health_score": {
                **cleaned_health,
                "label": get_score_label(cleaned_health["total"]),
            },
            "quality_scorecard": {
                "raw": raw_quality,
                "cleaned": cleaned_quality,
            },
            "anomaly_report": anomaly_report,
            "cleaning_report": cleaning_report,
            "pipeline_script": pipeline_script,
            "raw_preview": df_to_json_safe(_public_df(raw_with_row_id), max_rows=500),
            "cleaned_preview": df_to_json_safe(cleaned_public_df, max_rows=500),
            "modified_cells": change_bundle["modified_cells"],
            "change_log": change_bundle["change_log"],
            "change_summary": change_bundle["summary"],
            "approval_guardrails": review_summary.get("approval_guardrails", {}),
            "columns_info": _columns_info(cleaned_public_df),
            "review_summary": review_summary,
        })
    )


@router.get("/clean/{session_id}/review", summary="Get current review state and change log")
async def get_review_state(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DataSession).where(DataSession.session_id == session_id))
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    raw_with_row_id = _load_raw_with_row_id(session)
    cleaned_with_row_id = _load_cleaned_with_row_id(session)
    payload = _build_review_response(session, raw_with_row_id, cleaned_with_row_id)
    return JSONResponse(content=_convert_types(payload))


@router.get("/clean/{session_id}/data", summary="Get paginated cleaned or raw data rows")
async def get_paginated_data(
    session_id: str,
    page: int = 0,
    page_size: int = 100,
    dataset: str = "cleaned",  # "cleaned" or "raw"
    db: AsyncSession = Depends(get_db),
):
    """
    Server-side pagination endpoint for large datasets.
    Returns `page_size` rows starting from `page * page_size`.
    Max page_size capped at 1000 rows per request.
    """
    result = await db.execute(select(DataSession).where(DataSession.session_id == session_id))
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    page_size = min(max(1, page_size), 1000)
    page = max(0, page)

    try:
        if dataset == "raw":
            df = _public_df(_load_raw_with_row_id(session))
        else:
            df = _public_df(_load_cleaned_with_row_id(session))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load data: {str(exc)}")

    total_rows = int(df.shape[0])
    total_pages = max(1, -(-total_rows // page_size))  # ceiling division
    start = page * page_size
    end = min(start + page_size, total_rows)
    page_df = df.iloc[start:end]

    return JSONResponse(content=_convert_types({
        "success": True,
        "session_id": session_id,
        "dataset": dataset,
        "total_rows": total_rows,
        "total_pages": total_pages,
        "page": page,
        "page_size": page_size,
        "start_row": start,
        "end_row": end,
        "rows": df_to_json_safe(page_df, max_rows=page_size),
        "columns_info": _columns_info(df),
    }))


@router.get("/clean/{session_id}/download", summary="Download the cleaned dataset as CSV")
async def download_cleaned_dataset(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Download the cleaned dataset as a CSV file.
    Returns the original cleaned file (not modified by chatbot edits).
    """
    result = await db.execute(select(DataSession).where(DataSession.session_id == session_id))
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    if not session.cleaned_file_path or not os.path.exists(session.cleaned_file_path):
        raise HTTPException(status_code=404, detail="Cleaned dataset not found. Run cleaning first.")

    filename = f"{session.filename.rsplit('.', 1)[0]}_cleaned.csv"
    
    return FileResponse(
        path=session.cleaned_file_path,
        filename=filename,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/clean/{session_id}/edit", summary="Update a single cell in cleaned dataset")
async def edit_cleaned_cell(
    session_id: str,
    request: CellEditRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(DataSession).where(DataSession.session_id == session_id))
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    # Load the working copy (creates one if it doesn't exist)
    working_path, working_with_row_id = _get_or_create_working_copy(session)

    if request.row_index < 0 or request.row_index >= len(working_with_row_id):
        raise HTTPException(status_code=400, detail="Row index is out of range.")

    if request.column == ROW_ID_COL:
        raise HTTPException(status_code=400, detail="System row identifier cannot be edited.")

    if request.column not in working_with_row_id.columns:
        raise HTTPException(
            status_code=400,
            detail=f"Column '{request.column}' not found. Available: {list(_public_df(working_with_row_id).columns)}",
        )

    try:
        before_value = working_with_row_id.at[request.row_index, request.column]
        new_value = _coerce_value_for_column(working_with_row_id[request.column], request.value)
        working_with_row_id.at[request.row_index, request.column] = new_value
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update cell: {str(exc)}")

    # Save to the working copy (not the original cleaned file)
    working_with_row_id.to_csv(working_path, index=False)
    from app.services.cloud_storage import sync_to_cloud
    sync_to_cloud(working_path)
    await db.flush()
    await db.commit()

    working_public_df = _public_df(working_with_row_id)
    metrics = _session_metrics_payload(session, working_public_df)

    return JSONResponse(
        content=_convert_types({
            "success": True,
            "session_id": session_id,
            "status": session.status,
            "message": "Cell updated in chatbot working copy (original cleaned data preserved)",
            "edited_cell": {
                "change_id": f"cell:{int(working_with_row_id.at[request.row_index, ROW_ID_COL])}:{request.column}",
                "row": int(request.row_index),
                "source_row_id": int(working_with_row_id.at[request.row_index, ROW_ID_COL]),
                "column": request.column,
                "before": _safe_json_value(before_value),
                "after": _safe_json_value(new_value),
                "change_type": "manual_edit",
                "reason_tag": "manual_edit",
                "confidence": 1.0,
                "confidence_label": "high",
                "explanation": _explainability_for_change(
                    request.column,
                    _safe_json_value(before_value),
                    _safe_json_value(new_value),
                    "manual_edit",
                ),
            },
            "cleaned_preview": df_to_json_safe(working_public_df, max_rows=500),
            "cleaned_health_score": metrics["health"],
            "quality_scorecard": metrics.get("quality_scorecard"),
            "columns_info": _columns_info(working_public_df),
        })
    )


@router.post("/clean/{session_id}/feedback", summary="Submit review feedback and decisions")
async def submit_review_feedback(
    session_id: str,
    request: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    mongo_db=Depends(get_mongo_db),
):
    result = await db.execute(select(DataSession).where(DataSession.session_id == session_id))
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    review_summary = session.review_summary or {}
    decisions = review_summary.get("decisions", {})

    for item in request.per_change_actions:
        decisions[item.change_id] = item.action

    feedback_entry = {
        "approval_status": request.approval_status,
        "trust_score": request.trust_score,
        "comments": request.comments,
        "per_change_actions": [item.model_dump() for item in request.per_change_actions],
        "created_at": _utc_now_iso(),
    }

    feedback_history = review_summary.get("feedback_history", [])
    feedback_history.append(feedback_entry)

    strategy_feedback = review_summary.get("strategy_feedback", [])
    if request.strategy_feedback:
        strategy_feedback.append(
            {
                "details": request.strategy_feedback,
                "created_at": _utc_now_iso(),
            }
        )

    review_summary["decisions"] = decisions
    review_summary["feedback_history"] = feedback_history
    review_summary["strategy_feedback"] = strategy_feedback
    review_summary["workflow_state"] = _set_status_for_feedback(
        review_summary.get("workflow_state", session.status), request.approval_status
    )
    review_summary["updated_at"] = _utc_now_iso()
    review_summary = _sanitize_for_json(review_summary)

    session.review_summary = review_summary
    session.status = _set_status_for_feedback(session.status, request.approval_status)

    await db.flush()

    if mongo_db is not None:
        await mongo_db.processing_logs.insert_one(
            {
                "session_id": session_id,
                "event": "review_feedback",
                "approval_status": request.approval_status,
                "trust_score": request.trust_score,
                "strategy_feedback": request.strategy_feedback,
                "decision_count": len(request.per_change_actions),
            }
        )

    return JSONResponse(
        content=_convert_types({
            "success": True,
            "session_id": session_id,
            "status": session.status,
            "workflow_state": review_summary.get("workflow_state", session.status),
            "feedback": feedback_entry,
            "decision_count": len(decisions),
        })
    )


@router.post("/clean/{session_id}/revert", summary="Revert selected auto-clean changes")
async def revert_selected_changes(
    session_id: str,
    request: RevertChangesRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(DataSession).where(DataSession.session_id == session_id))
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    raw_with_row_id = _load_raw_with_row_id(session)
    cleaned_with_row_id = _load_cleaned_with_row_id(session)

    raw_indexed = raw_with_row_id.set_index(ROW_ID_COL, drop=False)
    reverted: List[str] = []
    skipped: List[Dict[str, Any]] = []

    for change_id in request.change_ids:
        parts = change_id.split(":")
        if len(parts) < 3 or parts[0] != "cell":
            skipped.append({"change_id": change_id, "reason": "Only cell-level changes are revertible."})
            continue

        try:
            row_id = int(parts[1])
            column = ":".join(parts[2:])
        except Exception:
            skipped.append({"change_id": change_id, "reason": "Invalid change id format."})
            continue

        if row_id not in raw_indexed.index:
            skipped.append({"change_id": change_id, "reason": "Source row not found in raw dataset."})
            continue

        if column not in cleaned_with_row_id.columns or column not in raw_with_row_id.columns:
            skipped.append({"change_id": change_id, "reason": "Column not available for reversion."})
            continue

        match_idx = cleaned_with_row_id.index[cleaned_with_row_id[ROW_ID_COL] == row_id].tolist()
        if not match_idx:
            skipped.append({"change_id": change_id, "reason": "Row was removed and cannot be restored here."})
            continue

        cleaned_with_row_id.at[match_idx[0], column] = raw_indexed.at[row_id, column]
        reverted.append(change_id)

    cleaned_with_row_id.to_csv(session.cleaned_file_path, index=False)
    from app.services.cloud_storage import sync_to_cloud
    sync_to_cloud(session.cleaned_file_path)

    cleaned_public_df = _public_df(cleaned_with_row_id)
    cleaned_health = compute_health_score(cleaned_public_df)

    change_bundle = _build_change_bundle(
        raw_with_row_id=raw_with_row_id,
        cleaned_with_row_id=cleaned_with_row_id,
        cleaning_report=session.cleaning_summary or {},
    )

    review_summary = session.review_summary or {}
    decisions = review_summary.get("decisions", {})
    for cid in reverted:
        decisions[cid] = "reverted"

    review_summary["decisions"] = decisions
    review_summary["changes"] = change_bundle["change_log"]
    review_summary["modified_cells"] = change_bundle["modified_cells"]
    review_summary["change_summary"] = change_bundle["summary"]
    review_summary["cleaned_health_score"] = cleaned_health["total"]
    review_summary["workflow_state"] = "revised"
    review_summary["updated_at"] = _utc_now_iso()
    review_summary = _sanitize_for_json(review_summary)

    session.review_summary = review_summary
    session.cleaned_rows = int(cleaned_public_df.shape[0])
    session.cleaned_cols = int(cleaned_public_df.shape[1])
    session.cleaned_health_score = cleaned_health["total"]
    session.status = "revised"

    await db.flush()

    return JSONResponse(
        content=_convert_types({
            "success": True,
            "session_id": session_id,
            "status": session.status,
            "reverted_change_ids": reverted,
            "skipped": skipped,
            "cleaned_health_score": {
                **cleaned_health,
                "label": get_score_label(cleaned_health["total"]),
            },
            "cleaned_preview": df_to_json_safe(cleaned_public_df, max_rows=500),
            "modified_cells": change_bundle["modified_cells"],
            "change_log": change_bundle["change_log"],
            "change_summary": change_bundle["summary"],
            "columns_info": _columns_info(cleaned_public_df),
        })
    )


@router.post("/clean/{session_id}/finalize", summary="Lock approved cleaned dataset and write changelog")
async def finalize_cleaned_dataset(
    session_id: str,
    request: FinalizeRequest,
    db: AsyncSession = Depends(get_db),
    mongo_db=Depends(get_mongo_db),
):
    result = await db.execute(select(DataSession).where(DataSession.session_id == session_id))
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    cleaned_with_row_id = _load_cleaned_with_row_id(session)
    cleaned_public_df = _public_df(cleaned_with_row_id)

    approved_path = os.path.join(settings.upload_dir, f"{session_id}_approved.csv")
    cleaned_public_df.to_csv(approved_path, index=False)
    from app.services.cloud_storage import sync_to_cloud
    sync_to_cloud(approved_path)

    review_summary = session.review_summary or {}
    history = review_summary.get("version_history", [])
    history.append(
        {
            "version": len(history) + 1,
            "status": "approved",
            "approved_file_path": approved_path,
            "notes": request.notes,
            "created_at": _utc_now_iso(),
        }
    )
    review_summary["version_history"] = history
    review_summary["workflow_state"] = "approved"
    review_summary["updated_at"] = _utc_now_iso()

    session.review_summary = review_summary
    session.approved_file_path = approved_path
    session.status = "approved"

    await db.flush()

    if mongo_db is not None:
        await mongo_db.processing_logs.insert_one(
            {
                "session_id": session_id,
                "event": "finalized",
                "approved_file_path": approved_path,
                "notes": request.notes,
            }
        )

    return JSONResponse(
        content=_convert_types({
            "success": True,
            "session_id": session_id,
            "status": session.status,
            "workflow_state": "approved",
            "approved_file_path": approved_path,
            "message": "Dataset approved and finalized.",
        })
    )


@router.get("/quality/session/{session_id}", summary="Get session-level quality scorecards and anomaly report")
async def get_session_quality(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(DataSession).where(DataSession.session_id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    raw_with_row_id = _load_raw_with_row_id(session)
    raw_df = _public_df(raw_with_row_id)
    raw_scorecard = compute_quality_scorecard(raw_df)

    cleaned_scorecard = None
    anomaly_report = None
    if session.cleaned_file_path and os.path.exists(session.cleaned_file_path):
        cleaned_df = _public_df(_load_cleaned_with_row_id(session))
        cleaned_scorecard = compute_quality_scorecard(cleaned_df)
        baseline_partner_profile = await _build_feed_baseline_partner_profile(db=db, current_session=session)
        anomaly_report = detect_anomalies(
            raw_df=raw_df,
            cleaned_df=cleaned_df,
            baseline_partner_profile=baseline_partner_profile,
        )
        anomaly_report = _sanitize_for_json(anomaly_report)

    return JSONResponse(
        content=_convert_types({
            "success": True,
            "session_id": session_id,
            "scorecard": {
                "raw": raw_scorecard,
                "cleaned": cleaned_scorecard,
            },
            "anomaly_report": anomaly_report,
        })
    )


@router.get("/quality/feeds", summary="Get feed-level quality score summary")
async def get_feed_quality_summary(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(DataSession).order_by(desc(DataSession.created_at)).limit(max(1, min(limit * 25, 250)))
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    grouped: Dict[str, List[DataSession]] = {}
    for session in sessions:
        key = session.filename or "unknown"
        grouped.setdefault(key, []).append(session)

    feed_rows = []
    for filename, feed_sessions in grouped.items():
        if not feed_sessions:
            continue

        raw_scores = [float(s.raw_health_score) for s in feed_sessions if s.raw_health_score is not None]
        cleaned_scores = [float(s.cleaned_health_score) for s in feed_sessions if s.cleaned_health_score is not None]
        latest = feed_sessions[0]

        avg_raw = round(float(np.mean(raw_scores)), 2) if raw_scores else None
        avg_cleaned = round(float(np.mean(cleaned_scores)), 2) if cleaned_scores else None
        avg_improvement = round(avg_cleaned - avg_raw, 2) if avg_raw is not None and avg_cleaned is not None else None

        latest_path = latest.approved_file_path or latest.cleaned_file_path or latest.file_path
        latest_scorecard = None
        if latest_path and os.path.exists(latest_path):
            try:
                df_latest = pd.read_csv(latest_path, low_memory=False)
                if ROW_ID_COL in df_latest.columns:
                    df_latest = df_latest.drop(columns=[ROW_ID_COL], errors="ignore")
                latest_scorecard = compute_quality_scorecard(df_latest)
            except Exception:
                latest_scorecard = None

        feed_rows.append(
            {
                "feed_name": filename,
                "sessions": len(feed_sessions),
                "latest_session_id": latest.session_id,
                "avg_raw_health": avg_raw,
                "avg_cleaned_health": avg_cleaned,
                "avg_improvement": avg_improvement,
                "latest_quality_scorecard": latest_scorecard,
            }
        )

    feed_rows.sort(key=lambda row: row.get("sessions", 0), reverse=True)
    limited_rows = feed_rows[: max(1, min(limit, 100))]

    return JSONResponse(
        content=_convert_types({
            "success": True,
            "feeds": limited_rows,
            "count": len(limited_rows),
        })
    )


@router.get("/export/{session_id}", summary="Download the auto-generated Python cleaning script")
async def export_pipeline(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(DataSession).where(DataSession.session_id == session_id))
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    if session.status not in ("cleaned", "under_review", "revised", "approved", "visualized"):
        raise HTTPException(
            status_code=400,
            detail="Data must be cleaned before exporting the pipeline.",
        )

    raw_with_row_id = _load_raw_with_row_id(session)
    raw_df = _public_df(raw_with_row_id)

    engine = CleaningEngine(raw_df)
    _, _, operations = engine.clean(
        missing_strategy=session.missing_strategy or "mean",
        outlier_strategy=session.outlier_strategy or "iqr",
    )

    script = generate_pipeline_script(
        filename=session.filename,
        operations=operations,
        missing_strategy=session.missing_strategy or "mean",
        outlier_strategy=session.outlier_strategy or "iqr",
    )

    return PlainTextResponse(
        content=script,
        headers={
            "Content-Disposition": f'attachment; filename="statsflow_pipeline_{session_id[:8]}.py"'
        },
        media_type="text/plain",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Feature Engineering Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/clean/{session_id}/feature-engineering/suggest",
    summary="Ask AI to suggest new features for the cleaned dataset",
)
async def suggest_features_endpoint(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Analyzes the cleaned dataset and uses an LLM to propose meaningful
    new engineered features (ratios, transforms, interactions, binning, etc.).
    Returns a list of validated, previewable feature specs for the user to review.
    """
    from app.services.feature_engineering_service import suggest_features

    result = await db.execute(select(DataSession).where(DataSession.session_id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    # Prefer approved → cleaned → raw
    target_path = (
        session.approved_file_path
        or session.cleaned_file_path
        or session.file_path
    )
    if not target_path or not os.path.exists(target_path):
        raise HTTPException(status_code=404, detail="No dataset found. Run cleaning first.")

    try:
        df = pd.read_csv(target_path, low_memory=False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load dataset: {exc}")

    df = _ensure_row_id(df)

    suggestions = await suggest_features(df)

    return JSONResponse(content=_convert_types({
        "success": True,
        "session_id": session_id,
        "suggestion_count": len(suggestions),
        "suggestions": suggestions,
    }))


@router.post(
    "/clean/{session_id}/feature-engineering/apply",
    summary="Apply AI-selected features to the cleaned dataset",
)
async def apply_features_endpoint(
    session_id: str,
    request: FeatureEngineeringApplyRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Applies the user-approved feature specs to the cleaned dataset,
    saves the updated CSV, and returns the new column info + preview.
    """
    from app.services.feature_engineering_service import apply_features

    result = await db.execute(select(DataSession).where(DataSession.session_id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    if not request.selected_features:
        raise HTTPException(status_code=422, detail="No features selected to apply.")

    target_path = session.cleaned_file_path or session.file_path
    if not target_path or not os.path.exists(target_path):
        raise HTTPException(status_code=404, detail="No cleaned dataset found. Run cleaning first.")

    try:
        df = pd.read_csv(target_path, low_memory=False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load dataset: {exc}")

    df = _ensure_row_id(df)

    updated_df, apply_log = apply_features(df, request.selected_features)

    # Overwrite the cleaned file with new features included
    updated_df.to_csv(target_path, index=False)

    # Update session metadata
    public_updated = _public_df(updated_df)
    session.cleaned_cols = int(public_updated.shape[1])
    session.cleaned_health_score = compute_health_score(public_updated)["total"]
    await db.flush()

    return JSONResponse(content=_convert_types({
        "success": True,
        "session_id": session_id,
        "features_applied": len([f for f in apply_log if f["status"] == "applied"]),
        "apply_log": apply_log,
        "new_shape": {
            "rows": int(public_updated.shape[0]),
            "columns": int(public_updated.shape[1]),
        },
        "columns_info": _columns_info(public_updated),
        "cleaned_preview": df_to_json_safe(public_updated, max_rows=100),
    }))
