"""Application configuration loaded from environment variables via pydantic-settings."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

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
    ollama_vision_model: str = "qwen3-vl:4b"
    ollama_embedding_model: str = "nomic-embed-text"
    ollama_embedding_revision: str = "nomic-embed-text-v1"
    ollama_embedding_dimension: int = 768
    ollama_request_timeout: int = 120
    ollama_num_parallel: int = 2
    laya_model: str = "laya:latest"
    laya_rag_evidence_mode: Literal["off", "observe", "enforce"] = "off"
    laya_rag_rewrite_mode: Literal["off", "observe", "enforce"] = "off"
    laya_request_timeout_ms: int = Field(default=250, ge=10, le=5_000)

    # ── Hybrid vector store ─────────────────────────────────────────────
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection_name: str = "documents"
    fastembed_cache_path: Path = Path("./data/fastembed")
    rag_bm25_language: str = "english"

    # ── Optional specialist integrations ────────────────────────────────
    finnhub_api_key: str | None = None
    market_data_cache_seconds: int = 60
    comfyui_url: str = "http://localhost:8188"
    agent_workspace_root: Path = Path("./workspace")
    github_app_client_id: str | None = None
    github_app_client_secret: str | None = None
    github_app_callback_url: str | None = None
    github_app_slug: str | None = None
    github_frontend_url: str = "http://localhost:3000"
    github_token_encryption_key: str | None = None
    github_api_url: str = "https://api.github.com"
    github_oauth_url: str = "https://github.com/login/oauth"

    # ── Meeting transcription ───────────────────────────────────────────
    asr_model_dir: str | None = None
    asr_model_name: str = "small.en"
    asr_backend: Literal["faster-whisper", "mlx-whisper"] = "faster-whisper"
    meeting_audio_queue_size: int = 128
    meeting_pcm_window_ms: int = 2_000
    meeting_enable_rag: bool = False

    # ── Databases ───────────────────────────────────────────────────────
    sql_database_url: str = "sqlite+aiosqlite:///./data/demo.db"
    app_database_url: str = "sqlite+aiosqlite:///./data/app.db"

    # ── Document Upload ─────────────────────────────────────────────────
    max_upload_size_mb: int = 50
    upload_dir: str = "./data/uploads"
    allowed_extensions: str = (
        ".pdf,.docx,.xlsx,.pptx,.csv,.html,.md,.txt,.png,.jpg,.jpeg,.tiff,.bmp,.webp"
    )
    pdf_parser: Literal["pymupdf", "docling"] = "pymupdf"
    docling_artifacts_path: str | None = None

    # ── API Server ──────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = Field(default=["http://localhost:3000"])
    meeting_allowed_origins: list[str] = Field(default=[])
    auth_cookie_secure: bool = True
    auth_session_ttl_hours: int = Field(default=12, ge=1, le=720)
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
