"""
StatsFlow Visualization Router
--------------------------------
Handles Phase 3: Chart data generation and insight computation.

Endpoint: GET /api/visualize/{session_id}
"""

import os
import pandas as pd
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db, get_mongo_db
from app.models.postgres_models import DataSession
from app.services.visualization_service import generate_chart_data, generate_recommended_charts
from app.services.insights_service import generate_insights
from app.utils.helpers import get_column_types
import logging

router = APIRouter(prefix="/api", tags=["Visualization"])
logger = logging.getLogger(__name__)


@router.get("/visualize/{session_id}", summary="Get chart data and AI insights for cleaned dataset")
async def get_visualizations(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    mongo_db=Depends(get_mongo_db),
):
    """
    Phase 3 Endpoint: Visualization & Insights Generation

    Workflow:
    1. Verify session is in 'cleaned' state
    2. Load cleaned DataFrame from disk
    3. Generate chart data payloads (histograms, bars, correlation, scatter, boxplot)
    4. Run SLR-based insight generation
    5. Update session status to 'visualized'
    6. Return charts + insights JSON
    """
    # ── Load Session ──────────────────────────────────────────────────────────
    result = await db.execute(
        select(DataSession).where(DataSession.session_id == session_id)
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    if session.status == "uploaded":
        raise HTTPException(
            status_code=400,
            detail="Dataset must be cleaned before generating visualizations."
        )

    cleaned_path = session.approved_file_path or session.cleaned_file_path
    if not cleaned_path or not os.path.exists(cleaned_path):
        raise HTTPException(status_code=404, detail="Cleaned data file not found.")

    # ── Load Cleaned DataFrame ────────────────────────────────────────────────
    try:
        df = pd.read_csv(cleaned_path, low_memory=False)
        if "__sf_row_id" in df.columns:
            df = df.drop(columns=["__sf_row_id"], errors="ignore")
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load cleaned data: {str(exc)}"
        )

    # ── Generate Charts ───────────────────────────────────────────────────────
    charts = generate_chart_data(df)
    recommended_charts = generate_recommended_charts(df)

    # ── Generate Text Insights ────────────────────────────────────────────────
    insights = generate_insights(df)

    # ── Update Status ─────────────────────────────────────────────────────────
    session.status = "visualized"
    await db.flush()

    # ── Log to MongoDB ────────────────────────────────────────────────────────
    if mongo_db is not None:
        await mongo_db.processing_logs.insert_one({
            "session_id": session_id,
            "event": "visualized",
            "charts_generated": len(charts),
            "recommended_generated": len(recommended_charts),
            "insights_generated": len(insights),
        })

    logger.info(
        f"Session {session_id}: generated {len(charts)} charts, "
        f"{len(recommended_charts)} recommended charts, "
        f"{len(insights)} insights"
    )

    return JSONResponse(content={
        "success": True,
        "session_id": session_id,
        "charts": charts,
        "recommended_charts": recommended_charts,
        "insights": insights,
        "column_types": get_column_types(df),
        "shape": {"rows": int(df.shape[0]), "columns": int(df.shape[1])},
    })