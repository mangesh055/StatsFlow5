"""
StatsFlow Database Module
==========================
Uses:
  - SQLite via aiosqlite (zero setup, auto-creates statsflow.db)
  - MongoDB via motor (optional, app works fine without it)
"""

import logging
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

logger = logging.getLogger(__name__)

# ── Detect database type ──────────────────────────────────────────
IS_SQLITE = settings.database_url.startswith("sqlite")

# ── SQLAlchemy Engine ─────────────────────────────────────────────
if IS_SQLITE:
    engine = create_async_engine(
        url=settings.database_url,
        echo=settings.debug,
        connect_args={"check_same_thread": False},
    )
    logger.info("Database engine → SQLite (statsflow.db)")
else:
    import uuid
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(
        url=settings.database_url,
        echo=settings.debug,
        poolclass=NullPool,
        connect_args={
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4().hex}__",
            "statement_cache_size": 0
        }
    )
    logger.info("Database engine → PostgreSQL (PgBouncer compatible)")

# ── Session Factory ───────────────────────────────────────────────
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# ── Declarative Base ──────────────────────────────────────────────
class Base(DeclarativeBase):
    pass

# ── Session Dependency ────────────────────────────────────────────
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.error(f"DB session error: {exc}")
            raise
        finally:
            await session.close()

# ── Table Creation ────────────────────────────────────────────────
async def create_tables():
    from app.models.postgres_models import DataSession  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_data_session_columns)
    db_label = "SQLite" if IS_SQLITE else "PostgreSQL"
    logger.info(f"✅ Tables created — {db_label}")


def _ensure_data_session_columns(sync_conn):
    """Best-effort additive migration for columns introduced after initial setup."""
    inspector = inspect(sync_conn)
    if "data_sessions" not in inspector.get_table_names():
        return

    existing_cols = {col["name"] for col in inspector.get_columns("data_sessions")}
    additions = {
        "approved_file_path": "TEXT",
        "review_summary": "JSON",
        "chatbot_working_file_path": "TEXT",
        "chat_history": "JSON",
    }

    for col_name, col_type in additions.items():
        if col_name in existing_cols:
            continue
        sync_conn.execute(text(f"ALTER TABLE data_sessions ADD COLUMN {col_name} {col_type}"))
        logger.info(f"Added missing column data_sessions.{col_name}")

# ── MongoDB (fully optional) ──────────────────────────────────────
mongo_client = None
mongo_db     = None

async def connect_mongo():
    global mongo_client, mongo_db

    # Try to import motor — if not installed, skip silently
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
    except ImportError:
        logger.warning(
            "⚠️  'motor' package not installed.\n"
            "   Run: pip install motor pymongo\n"
            "   MongoDB features (chat history, logs) are disabled."
        )
        mongo_db = None
        return

    # Try to connect — if MongoDB not running, skip silently
    try:
        mongo_client = AsyncIOMotorClient(
            settings.mongodb_url,
            serverSelectionTimeoutMS=3000,
        )
        await mongo_client.admin.command("ping")
        mongo_db = mongo_client[settings.mongodb_db_name]
        logger.info(f"✅ MongoDB connected — '{settings.mongodb_db_name}'")

    except Exception as exc:
        logger.warning(
            f"⚠️  MongoDB not available — {exc}\n"
            f"   Chat history and logs are disabled.\n"
            f"   Install MongoDB or ignore this warning.\n"
            f"   All other features work normally."
        )
        mongo_client = None
        mongo_db     = None

async def disconnect_mongo():
    global mongo_client
    if mongo_client is not None:
        mongo_client.close()
        logger.info("MongoDB connection closed.")

def get_mongo_db():
    return mongo_db