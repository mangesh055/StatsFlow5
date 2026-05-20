"""
StatsFlow Chatbot Router
-------------------------
Handles Phase 4: Agentic Chatbot Q&A

Endpoints:
  POST /api/chat/{session_id}         — Send a message and get a response
  GET  /api/chat/{session_id}/history — Retrieve conversation history
  DELETE /api/chat/{session_id}       — Clear conversation history
"""

import os
import json
import pandas as pd
import shutil
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field
from typing import List, Dict, Any

from app.database import get_db, get_mongo_db
from app.models.postgres_models import DataSession
from app.services.chatbot_service import chat_with_dataset
from app.services.quality_scorecard import compute_quality_scorecard
from app.services.anomaly_detection import detect_anomalies
from app.utils.helpers import df_to_json_safe, get_column_types
from app.config import settings
import logging

router = APIRouter(prefix="/api", tags=["Chatbot"])
logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    """Request body for a chat message."""
    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="User message to the AI chatbot"
    )
    history: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Optional client-side history fallback when server-side chat history is unavailable"
    )
    thread_id: str = Field(
        default="default",
        description="ID of the chat thread"
    )


@router.post("/chat/{session_id}", summary="Chat with AI about your dataset")
async def chat(
    session_id: str,
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    mongo_db=Depends(get_mongo_db),
):
    """
    Phase 4 Endpoint: Agentic Chatbot Interaction

    Workflow:
    1. Load session and cleaned DataFrame
    2. Load conversation history from MongoDB
    3. Pass message + context to chatbot service (Claude API)
    4. If action detected, update DataFrame and save to disk
    5. Persist updated conversation history to MongoDB
    6. Return AI response and action details
    """
    # ── Load Session ──────────────────────────────────────────────────────────
    result = await db.execute(
        select(DataSession).where(DataSession.session_id == session_id)
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    active_path = session.approved_file_path or session.cleaned_file_path
    if not active_path or not os.path.exists(active_path):
        raise HTTPException(
            status_code=400,
            detail="Data must be cleaned before using the chatbot."
        )

    # ── Load Cleaned DataFrame ────────────────────────────────────────────────
    try:
        df = pd.read_csv(active_path, low_memory=False)
        if "__sf_row_id" in df.columns:
            df = df.drop(columns=["__sf_row_id"], errors="ignore")
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not load cleaned data: {str(exc)}"
        )

    # ── Load Conversation History from Postgres ────────────────────────
    chat_data = session.chat_history or {"threads": []}
    
    # Handle legacy list structure
    if isinstance(chat_data, list):
        chat_data = {
            "threads": [{
                "thread_id": "default",
                "title": "New Chat",
                "messages": chat_data
            }]
        }
    
    threads = chat_data.get("threads", [])
    current_thread = next((t for t in threads if t.get("thread_id") == request.thread_id), None)
    
    if current_thread is None:
        current_thread = {
            "thread_id": request.thread_id,
            "title": request.message[:30] + ("..." if len(request.message) > 30 else ""),
            "messages": []
        }
        threads.append(current_thread)
    
    conversation_history = current_thread.get("messages", [])

    # Fallback to client-provided history if server-side history is unavailable.
    if not conversation_history and request.history:
        conversation_history = [
            {
                "role": str(item.get("role", "")).strip(),
                "content": str(item.get("content", "")).strip(),
                "action": item.get("action"),
            }
            for item in request.history
            if str(item.get("role", "")).strip() and str(item.get("content", "")).strip()
        ]

    # Keep up to last 30 messages for stronger follow-up grounding.
    conversation_history = conversation_history[-30:]

    # ── Call Chatbot Service ──────────────────────────────────────────────────
    response_message, action_performed, updated_df, response_meta = await chat_with_dataset(
        message=request.message,
        df=df,
        conversation_history=conversation_history,
    )

    # ── Save Updated DataFrame if Action Was Performed ────────────────────────
    active_df = df
    anomaly_report = None
    quality_scorecard = None
    if updated_df is not None:
        # Create a versioned backup of the current cleaned file before overwriting
        try:
            if session.cleaned_file_path and os.path.exists(session.cleaned_file_path):
                versions_root = os.path.join(os.path.dirname(session.cleaned_file_path), "versions", session.session_id)
                Path(versions_root).mkdir(parents=True, exist_ok=True)
                timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
                backup_name = f"{timestamp}.csv"
                backup_path = os.path.join(versions_root, backup_name)
                shutil.copy(session.cleaned_file_path, backup_path)

                # Record version metadata into session.review_summary
                review = session.review_summary or {}
                versions = review.get("versions", [])
                versions.append({
                    "path": backup_path,
                    "filename": backup_name,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "trigger": "chatbot_action",
                    "action": action_performed,
                })
                review["versions"] = versions
                session.review_summary = review

        except Exception as exc:
            # Non-fatal: log and continue to save the updated DataFrame
            from app.services import chatbot_service as _cs
            _cs.logger.warning(f"Failed to create version backup: {exc}")

        updated_df.to_csv(session.cleaned_file_path, index=False)
        
        from app.services.cloud_storage import sync_to_cloud
        sync_to_cloud(session.cleaned_file_path)
        session.cleaned_rows = int(updated_df.shape[0])
        session.cleaned_cols = int(updated_df.shape[1])
        await db.flush()
        active_df = updated_df
        quality_scorecard = compute_quality_scorecard(active_df)
        anomaly_report = detect_anomalies(raw_df=df, cleaned_df=active_df)
        logger.info(
            f"Session {session_id}: DataFrame updated via agentic action. "
            f"New shape: {updated_df.shape}"
        )

    column_types = get_column_types(active_df)
    columns_info = [
        {
            "name": col,
            "type": column_types[col],
            "dtype": str(active_df[col].dtype),
            "missing_count": int(active_df[col].isnull().sum()),
        }
        for col in active_df.columns
    ]

    # ── Persist Chat History to MongoDB ──────────────────────────────────────
    new_user_message = {"role": "user", "content": request.message}
    new_assistant_message = {
        "role": "assistant",
        "content": response_message,
        "action": action_performed,
        "meta": response_meta,
    }

    conversation_history.append(new_user_message)
    conversation_history.append(new_assistant_message)
    
    current_thread["messages"] = conversation_history
    chat_data["threads"] = threads
    session.chat_history = chat_data
    
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(session, "chat_history")
    await db.commit()

    if mongo_db is not None:
        await mongo_db.chat_history.update_one(
            {"session_id": session_id},
            {"$set": {"session_id": session_id, "threads": threads}},
            upsert=True,
        )

    logger.info(
        f"Session {session_id}: chat message processed. "
        f"Action: {action_performed is not None}"
    )

    return JSONResponse(content={
        "success": True,
        "session_id": session_id,
        "response": response_message,
        "action_performed": action_performed,
        "response_meta": response_meta,
        "cleaned_preview": df_to_json_safe(active_df, max_rows=500),
        "columns_info": columns_info,
        "cleaned_shape": {
            "rows": int(active_df.shape[0]),
            "columns": int(active_df.shape[1]),
        },
        "updated_shape": (
            {"rows": int(updated_df.shape[0]), "columns": int(updated_df.shape[1])}
            if updated_df is not None
            else None
        ),
        "quality_scorecard": quality_scorecard,
        "anomaly_report": anomaly_report,
    })


@router.get("/chat/{session_id}/history", summary="Retrieve chat history")
async def get_chat_history(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    mongo_db=Depends(get_mongo_db),
):
    """Return the full conversation threads for a session."""
    result = await db.execute(select(DataSession).where(DataSession.session_id == session_id))
    session = result.scalar_one_or_none()
    
    chat_data = {"threads": []}
    if session and session.chat_history:
        if isinstance(session.chat_history, list):
            chat_data = {
                "threads": [{
                    "thread_id": "default",
                    "title": "New Chat",
                    "messages": session.chat_history
                }]
            }
        else:
            chat_data = session.chat_history
    elif mongo_db is not None:
        doc = await mongo_db.chat_history.find_one({"session_id": session_id})
        if doc:
            if "threads" in doc:
                chat_data = {"threads": doc.get("threads", [])}
            elif "messages" in doc:
                chat_data = {
                    "threads": [{
                        "thread_id": "default",
                        "title": "New Chat",
                        "messages": doc.get("messages", [])
                    }]
                }

    return JSONResponse(content={
        "success": True,
        "session_id": session_id,
        "threads": chat_data.get("threads", []),
    })


@router.delete("/chat/{session_id}", summary="Clear conversation history")
async def clear_chat_history(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    mongo_db=Depends(get_mongo_db),
):
    """Delete all chat messages for a session, starting fresh."""
    result = await db.execute(select(DataSession).where(DataSession.session_id == session_id))
    session = result.scalar_one_or_none()
    if session:
        session.chat_history = []
        await db.commit()

    if mongo_db is not None:
        await mongo_db.chat_history.delete_one({"session_id": session_id})

    return JSONResponse(content={
        "success": True,
        "message": "Chat history cleared.",
    })


class RollbackRequest(BaseModel):
    """Request body for rollback endpoint."""
    filename: str = Field(..., description="Version filename to restore (e.g. 20240501T123000Z.csv)")


class CommitRequest(BaseModel):
    """Request body for manual commit endpoint."""
    message: str = Field(..., description="User provided commit message")


@router.post("/chat/{session_id}/commit", summary="Manually commit current dataset state")
async def commit_version(
    session_id: str,
    request: CommitRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DataSession).where(DataSession.session_id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    if not session.cleaned_file_path or not os.path.exists(session.cleaned_file_path):
        raise HTTPException(status_code=400, detail="No cleaned file to commit.")

    try:
        versions_root = os.path.join(os.path.dirname(session.cleaned_file_path), "versions", session.session_id)
        Path(versions_root).mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        backup_name = f"{timestamp}.csv"
        backup_path = os.path.join(versions_root, backup_name)
        
        import shutil
        shutil.copy(session.cleaned_file_path, backup_path)

        review = session.review_summary or {}
        versions = review.get("versions", [])
        versions.insert(0, {
            "path": backup_path,
            "filename": backup_name,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "trigger": "manual_commit",
            "action": {"operation": request.message},
        })
        review["versions"] = versions
        session.review_summary = review
        
        # We need to tell SQLAlchemy that the JSON column changed
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(session, "review_summary")
        await db.commit()
        
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to commit version: {exc}")

    return JSONResponse(content={"success": True, "message": "Commit created.", "session_id": session_id})


@router.get("/chat/{session_id}/versions", summary="List saved cleaned-file versions")
async def list_versions(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DataSession).where(DataSession.session_id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    versions = []
    # Prefer recorded review_summary metadata
    try:
        review = session.review_summary or {}
        versions = review.get("versions", [])
    except Exception:
        versions = []

    # Fall back to filesystem listing if metadata absent
    if not versions and session.cleaned_file_path:
        versions_root = os.path.join(os.path.dirname(session.cleaned_file_path), "versions", session.session_id)
        if os.path.exists(versions_root):
            for fname in sorted(os.listdir(versions_root), reverse=True):
                fpath = os.path.join(versions_root, fname)
                if os.path.isfile(fpath):
                    versions.append({"filename": fname, "path": fpath})

    return JSONResponse(content={"success": True, "session_id": session_id, "versions": versions})


@router.post("/chat/{session_id}/rollback", summary="Rollback cleaned file to a saved version")
async def rollback_version(
    session_id: str,
    request: RollbackRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DataSession).where(DataSession.session_id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    if not session.cleaned_file_path:
        raise HTTPException(status_code=400, detail="No cleaned file to rollback.")

    versions_root = os.path.join(os.path.dirname(session.cleaned_file_path), "versions", session.session_id)
    target_path = os.path.join(versions_root, request.filename)
    if not os.path.exists(target_path):
        raise HTTPException(status_code=404, detail="Requested version not found.")

    try:
        shutil.copy(target_path, session.cleaned_file_path)
        # Update session metadata
        df = pd.read_csv(session.cleaned_file_path, low_memory=False)
        session.cleaned_rows = int(df.shape[0])
        session.cleaned_cols = int(df.shape[1])
        review = session.review_summary or {}
        rollbacks = review.get("rollbacks", [])
        rollbacks.append({
            "restored_from": request.filename,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "trigger": "user_rollback",
        })
        review["rollbacks"] = rollbacks
        session.review_summary = review
        session.status = "revised"
        await db.flush()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Rollback failed: {exc}")

    return JSONResponse(content={"success": True, "message": "Rollback completed.", "session_id": session_id})