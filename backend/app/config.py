"""
StatsFlow Configuration Module
-------------------------------
Centralized settings management using Pydantic BaseSettings.
All environment variables are loaded from the .env file.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import List
import os


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ENV_FILE_PATH = os.path.join(BACKEND_ROOT, ".env")


class Settings(BaseSettings):
    """Application-wide settings loaded from environment variables."""

    # App Identity
    app_name: str = Field(default="StatsFlow", description="Application name")
    app_version: str = Field(default="1.0.0", description="Application version")
    debug: bool = Field(default=True, description="Debug mode toggle")
    secret_key: str = Field(
        default="statsflow-dev-secret-key",
        description="JWT/session secret key"
    )

    # PostgreSQL — stores relational project/session metadata
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:password@localhost:5432/statsflow_db",
        description="Async PostgreSQL connection string"
    )

    # MongoDB — stores flexible processing logs and chat history
    mongodb_url: str = Field(
        default="mongodb://localhost:27017",
        description="MongoDB connection URL"
    )
    mongodb_db_name: str = Field(
        default="statsflow_logs",
        description="MongoDB database name"
    )

    # LLM API providers
    anthropic_api_key: str = Field(
        default="",
        description="Anthropic Claude API key (legacy/optional)"
    )
    chat_api_key: str = Field(
        default="",
        description="API key for OpenAI-compatible providers (OpenAI, Groq, OpenRouter, local gateway)"
    )
    gemini_api_key: str = Field(
        default="",
        description="Google Gemini API key (preferred when CHAT_PROVIDER=gemini)"
    )
    groq_api_key: str = Field(
        default="",
        description="Groq API key (preferred when CHAT_PROVIDER=groq)"
    )
    chat_base_url: str = Field(
        default="",
        description="Optional base URL for OpenAI-compatible API endpoints"
    )
    groq_base_url: str = Field(
        default="https://api.groq.com/openai/v1",
        description="Base URL for Groq's OpenAI-compatible API"
    )
    chat_provider: str = Field(
        default="groq",
        description="Chat provider: 'groq', 'openai', 'langchain', 'anthropic', 'local', or 'auto'"
    )
    chat_model: str = Field(
        default="llama-3.3-70b-versatile",
        description="Model name used by remote chat providers"
    )

    # CORS — allowed frontend origins
    allowed_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        description="Comma-separated CORS origins"
    )

    # File handling
    max_file_size_mb: int = Field(default=50, description="Max upload file size in MB")
    upload_dir: str = Field(default="uploads", description="Local directory for uploaded files")

    @property
    def allowed_origins_list(self) -> List[str]:
        """Parse comma-separated CORS origins into a Python list."""
        return [origin.strip() for origin in self.allowed_origins.split(",")]

    @property
    def max_file_size_bytes(self) -> int:
        """Convert MB limit to bytes for validation."""
        return self.max_file_size_mb * 1024 * 1024

    def ensure_upload_dir(self):
        """Create upload directory if it does not exist."""
        upload_path = (
            self.upload_dir
            if os.path.isabs(self.upload_dir)
            else os.path.join(BACKEND_ROOT, self.upload_dir)
        )
        os.makedirs(upload_path, exist_ok=True)

    # Supabase Storage Configuration
    supabase_url: str = Field(default="", description="Supabase project URL")
    supabase_key: str = Field(default="", description="Supabase service role / anon key")
    supabase_bucket: str = Field(default="statsflow-datasets", description="Supabase storage bucket name")

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        case_sensitive=False
    )


# Singleton settings instance — import this across the application
settings = Settings()
settings.ensure_upload_dir()