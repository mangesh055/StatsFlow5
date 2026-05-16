"""
StatsFlow PostgreSQL ORM Models
--------------------------------
Defines the relational schema stored in PostgreSQL.
Each processing session for a user's dataset is tracked here.
"""

from sqlalchemy import Column, String, Float, Integer, DateTime, Text, JSON
from sqlalchemy.sql import func
from app.database import Base


class DataSession(Base):
    """
    Represents a single user's data processing session.

    Lifecycle:
        uploaded → cleaned → visualized → chatting

    Fields are updated as the user progresses through each phase.
    """
    __tablename__ = "data_sessions"

    # ── Identity ───────────────────────────────────────────────────────────────
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(String(36), unique=True, index=True, nullable=False,
                        comment="UUID identifying this processing session")

    # ── File Metadata ──────────────────────────────────────────────────────────
    filename = Column(String(255), nullable=False,
                      comment="Original uploaded filename")
    file_path = Column(String(512), nullable=True,
                       comment="Filesystem path to the raw uploaded file")
    cleaned_file_path = Column(String(512), nullable=True,
                               comment="Filesystem path to the cleaned CSV file")
    chatbot_working_file_path = Column(String(512), nullable=True,
                                       comment="Filesystem path to the working copy for chatbot edits")
    approved_file_path = Column(String(512), nullable=True,
                                comment="Filesystem path to the user-approved final CSV file")

    # ── Dataset Dimensions ─────────────────────────────────────────────────────
    original_rows = Column(Integer, nullable=True, comment="Row count before cleaning")
    original_cols = Column(Integer, nullable=True, comment="Column count before cleaning")
    cleaned_rows = Column(Integer, nullable=True, comment="Row count after cleaning")
    cleaned_cols = Column(Integer, nullable=True, comment="Column count after cleaning")

    # ── Health Scores (0-100) ──────────────────────────────────────────────────
    raw_health_score = Column(Float, nullable=True, comment="Quality score of raw data")
    cleaned_health_score = Column(Float, nullable=True, comment="Quality score after cleaning")

    # ── Cleaning Configuration ─────────────────────────────────────────────────
    missing_strategy = Column(String(50), nullable=True,
                              comment="Strategy used for missing value imputation")
    outlier_strategy = Column(String(50), nullable=True,
                              comment="Strategy used for outlier treatment")
    cleaning_summary = Column(JSON, nullable=True,
                              comment="JSON summary of all cleaning operations applied")
    review_summary = Column(JSON, nullable=True,
                            comment="JSON summary of review decisions and version history")
    chat_history = Column(JSON, nullable=True,
                          comment="JSON array of chat conversation messages")

    # ── Status Tracking ────────────────────────────────────────────────────────
    status = Column(
        String(20),
        nullable=False,
        default="uploaded",
        comment="Session status: uploaded | cleaned | under_review | revised | approved | visualized"
    )

    # ── Timestamps ─────────────────────────────────────────────────────────────
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return (
            f"<DataSession session_id={self.session_id} "
            f"file={self.filename} status={self.status}>"
        )