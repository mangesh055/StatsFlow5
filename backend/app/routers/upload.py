"""
StatsFlow Upload Router
------------------------
Handles Phase 1: Raw data ingestion.
Endpoint: POST /api/upload

Accepts CSV or Excel files, parses them using Pandas,
computes the raw Data Health Score, and creates a session record.
"""

import os
import math
import pandas as pd
from fastapi import APIRouter, File, UploadFile, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_mongo_db
from app.models.postgres_models import DataSession
from app.services.health_score import compute_health_score, get_score_label
from app.services.quality_scorecard import compute_quality_scorecard
from app.services.anomaly_detection import detect_anomalies
from app.utils.helpers import df_to_json_safe, get_column_types, generate_session_id, _convert_types
from app.config import settings
import logging

router = APIRouter(prefix="/api", tags=["Upload"])
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}


def _safe_rounded(value, ndigits: int = 4):
    """Return a JSON-safe rounded float, or None for NaN/Inf values."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, ndigits)


@router.post("/upload", summary="Upload raw dataset and receive initial health score")
async def upload_dataset(
    file: UploadFile = File(..., description="CSV or Excel dataset file"),
    db: AsyncSession = Depends(get_db),
    mongo_db=Depends(get_mongo_db),
):
    """
    Phase 1 Endpoint: Raw Data Ingestion

    Workflow:
    1. Validate the uploaded file (type and size)
    2. Parse using Pandas
    3. Compute the raw Data Health Score
    4. Store file to disk and metadata to PostgreSQL
    5. Log the upload event to MongoDB
    6. Return session_id, health score, and data preview
    """
    # ── Validate File Type ────────────────────────────────────────────────────
    filename = file.filename or "dataset"
    ext = os.path.splitext(filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {ALLOWED_EXTENSIONS}"
        )

    # ── Read File Content ─────────────────────────────────────────────────────
    content = await file.read()

    if len(content) > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum size of {settings.max_file_size_mb}MB"
        )

    # ── Parse with Pandas ─────────────────────────────────────────────────────
    try:
        import io
        if ext == ".csv":
            df = pd.read_csv(io.BytesIO(content), low_memory=False)
        else:
            df = pd.read_excel(io.BytesIO(content))
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Failed to parse file: {str(exc)}"
        )

    if df.empty:
        raise HTTPException(status_code=422, detail="Uploaded file contains no data.")

    if df.shape[1] < 1:
        raise HTTPException(
            status_code=422, detail="Dataset must have at least 1 column."
        )

    # ── Generate Session ID ───────────────────────────────────────────────────
    session_id = generate_session_id()

    # ── Save Raw File to Disk & Cloud ─────────────────────────────────────────
    raw_file_path = os.path.join(settings.upload_dir, f"{session_id}_raw.csv")
    df.to_csv(raw_file_path, index=False)
    
    from app.services.cloud_storage import sync_to_cloud
    sync_to_cloud(raw_file_path)

    # ── Compute Raw Health Score ──────────────────────────────────────────────
    health = compute_health_score(df)
    quality_scorecard = compute_quality_scorecard(df)
    anomaly_report = detect_anomalies(raw_df=df, cleaned_df=None)
    score_label = get_score_label(health["total"])

    # ── Analyze Columns ───────────────────────────────────────────────────────
    column_types = get_column_types(df)
    columns_info = []
    for col in df.columns:
        missing_pct = _safe_rounded(df[col].isnull().mean() * 100, 2)
        col_info = {
            "name": col,
            "type": column_types[col],
            "dtype": str(df[col].dtype),
            "missing_count": int(df[col].isnull().sum()),
            "missing_pct": missing_pct if missing_pct is not None else 0.0,
            "unique_count": int(df[col].nunique()),
        }
        if column_types[col] == "numeric":
            col_info["mean"] = _safe_rounded(df[col].mean(), 4)
            col_info["std"] = _safe_rounded(df[col].std(), 4)
        columns_info.append(col_info)

    # ── Store Session in PostgreSQL ───────────────────────────────────────────
    session_record = DataSession(
        session_id=session_id,
        filename=filename,
        file_path=raw_file_path,
        original_rows=int(df.shape[0]),
        original_cols=int(df.shape[1]),
        raw_health_score=health["total"],
        status="uploaded",
    )
    db.add(session_record)
    await db.flush()

    # ── Log Upload Event to MongoDB ───────────────────────────────────────────
    if mongo_db is not None:
        await mongo_db.processing_logs.insert_one({
            "session_id": session_id,
            "event": "upload",
            "filename": filename,
            "shape": {"rows": int(df.shape[0]), "cols": int(df.shape[1])},
            "raw_health_score": health["total"],
        })

    logger.info(f"Session {session_id}: uploaded '{filename}' "
                f"({df.shape[0]}×{df.shape[1]}), health={health['total']}")

    # ── Return Response ───────────────────────────────────────────────────────
    response_payload = {
        "success": True,
        "session_id": session_id,
        "filename": filename,
        "shape": {
            "rows": int(df.shape[0]),
            "columns": int(df.shape[1]),
        },
        "health_score": {
            **health,
            "label": score_label,
        },
        "quality_scorecard": {
            "raw": quality_scorecard,
            "cleaned": None,
        },
        "anomaly_report": anomaly_report,
        "columns_info": columns_info,
        "data_preview": df_to_json_safe(df, max_rows=500),
        "column_names": list(df.columns),
    }
    return JSONResponse(content=_convert_types(response_payload))


@router.get("/session/{session_id}", summary="Get existing session details")
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    from app.utils.helpers import df_to_json_safe, get_column_types
    from app.services.health_score import get_score_label
    import pandas as pd
    
    result = await db.execute(select(DataSession).where(DataSession.session_id == session_id))
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    response_payload = {
        "success": True,
        "session_id": session_id,
        "filename": session.filename,
        "status": session.status,
    }

    if session.file_path and not os.path.exists(session.file_path):
        from app.services.cloud_storage import ensure_local_copy
        basename = os.path.basename(session.file_path)
        if basename.endswith("_raw.csv"):
            object_name = f"raw/{basename}"
        elif basename.endswith("_cleaned.csv"):
            object_name = f"cleaned/{basename}"
        else:
            object_name = f"working/{basename}"
        ensure_local_copy(object_name, session.file_path)

    if session.file_path and os.path.exists(session.file_path):
        try:
            df = pd.read_csv(session.file_path, low_memory=False)
            columns_info = []
            column_types = get_column_types(df)
            for col in df.columns:
                if col == "__sf_row_id":
                    continue
                missing_pct = _safe_rounded(df[col].isnull().mean() * 100, 2)
                col_info = {
                    "name": col,
                    "type": column_types.get(col, "unknown"),
                    "dtype": str(df[col].dtype),
                    "missing_count": int(df[col].isnull().sum()),
                    "missing_pct": missing_pct if missing_pct is not None else 0.0,
                    "unique_count": int(df[col].nunique()),
                }
                columns_info.append(col_info)
            
            response_payload["raw"] = {
                "shape": {
                    "rows": int(session.original_rows) if session.original_rows else int(df.shape[0]),
                    "columns": int(session.original_cols) if session.original_cols else int(df.shape[1]),
                },
                "health_score": {
                    "total": session.raw_health_score,
                    "label": get_score_label(session.raw_health_score) if session.raw_health_score is not None else "Unknown",
                },
                "columns_info": columns_info,
                "data_preview": df_to_json_safe(df, max_rows=500),
                "column_names": [c for c in df.columns if c != "__sf_row_id"],
            }
        except Exception as e:
            logger.error(f"Error reading raw file for session {session_id}: {e}")

    return JSONResponse(content=_convert_types(response_payload))