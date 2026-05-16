"""
StatsFlow — FastAPI Application Entry Point
============================================
Run with:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
import os

from app.config import settings
from app.database import create_tables, connect_mongo, disconnect_mongo
from app.routers import upload, cleaning, visualization, chatbot

# ── Logging ───────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO if settings.debug else logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("statsflow")


# ── Lifespan ──────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 55)
    logger.info(f"  Starting {settings.app_name} v{settings.app_version}")
    logger.info("=" * 55)

    os.makedirs(settings.upload_dir, exist_ok=True)
    await create_tables()
    await connect_mongo()

    logger.info("✅ StatsFlow is ready.")
    logger.info("   API Docs : http://localhost:8000/docs")
    logger.info("   Frontend : http://localhost:3000")

    yield

    await disconnect_mongo()
    logger.info("StatsFlow shutdown complete.")


# ── App Instance ──────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    description="AI-Enabled Data Processing Platform — VIT Pune",
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ── CORS Middleware ───────────────────────────────────────────────
# Allow requests from React dev server on port 3000
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


# ── Routers ───────────────────────────────────────────────────────
app.include_router(upload.router)
app.include_router(cleaning.router)
app.include_router(visualization.router)
app.include_router(chatbot.router)


# ── Health Checks ─────────────────────────────────────────────────
@app.get("/", tags=["Health"])
async def root():
    return {
        "app":     settings.app_name,
        "version": settings.app_version,
        "status":  "running",
        "docs":    "/docs",
    }


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "healthy"}