"""Application configuration loaded from environment variables via pydantic-settings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the Local AI Application.

    All values are loaded from environment variables or a .env file
    at the project root. See .env.example for documentation of each field.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Ollama ──────────────────────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "llama3.1:8b"
    ollama_vision_model: str = "llama3.2-vision:11b"
    ollama_embedding_model: str = "nomic-embed-text"
    ollama_request_timeout: int = 120
    ollama_num_parallel: int = 2

    # ── Meeting transcription ───────────────────────────────────────────
    asr_model_dir: str | None = None
    asr_model_name: str = "small.en"
    meeting_audio_queue_size: int = 128
    meeting_pcm_window_ms: int = 2_000
    meeting_enable_rag: bool = False

    # ── Databases ───────────────────────────────────────────────────────
    sql_database_url: str = "sqlite+aiosqlite:///./data/demo.db"
    app_database_url: str = "sqlite+aiosqlite:///./data/app.db"

    # ── ChromaDB ────────────────────────────────────────────────────────
    chroma_persist_dir: str = "./data/chroma"
    chroma_collection_name: str = "documents"
    chroma_host: str | None = None
    chroma_port: int = 8000

    # ── Document Upload ─────────────────────────────────────────────────
    max_upload_size_mb: int = 50
    upload_dir: str = "./data/uploads"
    allowed_extensions: str = (
        ".pdf,.docx,.xlsx,.pptx,.csv,.html,.md,.txt,.png,.jpg,.jpeg,.tiff,.bmp"
    )

    # ── API Server ──────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = Field(default=["http://localhost:3000"])
    meeting_allowed_origins: list[str] = Field(default=[])
    log_level: str = "info"

    # ── RAG ─────────────────────────────────────────────────────────────
    rag_chunk_size: int = 1000
    rag_chunk_overlap: int = 200
    rag_top_k: int = 5
    rag_score_threshold: float = 0.4

    # ── SQL Agent ───────────────────────────────────────────────────────
    sql_max_rows: int = 100
    sql_allow_writes: bool = False
    sql_query_timeout_seconds: float = Field(default=30.0, gt=0)

    # ── Rate Limiting ──────────────────────────────────────────────────
    rate_limit_default: str = "60/minute"
    rate_limit_llm: str = "10/minute"
    rate_limit_embedding: str = "20/minute"
    rate_limit_upload: str = "20/minute"

    # ── MCP ─────────────────────────────────────────────────────────────
    mcp_servers_config: str = "./mcp_servers.json"

    # ── Computed properties ─────────────────────────────────────────────

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def allowed_extensions_set(self) -> set[str]:
        return {ext.strip().lower() for ext in self.allowed_extensions.split(",")}

    @property
    def upload_path(self) -> Path:
        path = Path(self.upload_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def chroma_path(self) -> Path:
        path = Path(self.chroma_persist_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        """Accept JSON array, comma-separated string, or list."""
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            # Try JSON first, then fall back to comma-separated
            v = v.strip()
            if v.startswith("["):
                import json

                return json.loads(v)
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @field_validator("meeting_allowed_origins", mode="before")
    @classmethod
    def parse_meeting_allowed_origins(cls, v: Any) -> list[str]:
        """Accept JSON or comma-separated meeting WebSocket origins."""
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            value = v.strip()
            if value.startswith("["):
                import json

                return json.loads(value)
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"debug", "info", "warning", "error", "critical"}
        if v.lower() not in allowed:
            msg = f"log_level must be one of {allowed}, got '{v}'"
            raise ValueError(msg)
        return v.lower()


# Module-level singleton — import this throughout the application.
settings = Settings()
