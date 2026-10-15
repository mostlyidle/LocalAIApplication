"""Tests for app.config — pydantic-settings configuration."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import Settings

# =============================================================================
# Helper to get clean Settings isolated from env and .env file
# =============================================================================

# Env vars set in conftest.py or the .env file that override code defaults.
_CONFTEST_ENV_KEYS = [
    "APP_DATABASE_URL",
    "SQL_DATABASE_URL",
    "QDRANT_COLLECTION_NAME",
    "UPLOAD_DIR",
    "LOG_LEVEL",
    "RATE_LIMIT_DEFAULT",
    "RATE_LIMIT_LLM",
    "RATE_LIMIT_EMBEDDING",
    "RATE_LIMIT_UPLOAD",
    "OLLAMA_CHAT_MODEL",
    "OLLAMA_VISION_MODEL",
    "RAG_SCORE_THRESHOLD",
]


def _clean_settings(**overrides) -> Settings:
    """Create a Settings instance isolated from env vars and .env files."""
    # Build an env dict that removes conftest overrides
    clean_env = {k: v for k, v in os.environ.items() if k not in _CONFTEST_ENV_KEYS}
    with patch.dict(os.environ, clean_env, clear=True):
        return Settings(_env_file=None, **overrides)


# =============================================================================
# Code-level defaults (tested in isolation)
# =============================================================================


class TestCodeDefaults:
    """Verify code-level default values (isolated from env vars and .env file)."""

    def test_ollama_defaults(self):
        s = _clean_settings()
        assert s.ollama_base_url == "http://localhost:11434"
        assert s.ollama_embedding_model == "nomic-embed-text"
        assert s.ollama_request_timeout == 120
        assert s.ollama_num_parallel == 2
        # These use the code defaults now
        assert s.ollama_chat_model == "llama3.1:8b"
        assert s.ollama_vision_model == "qwen3-vl:4b"

    def test_database_urls_have_sqlite(self):
        s = _clean_settings()
        assert "sqlite" in s.sql_database_url
        assert "sqlite" in s.app_database_url

    def test_qdrant_defaults(self):
        s = _clean_settings()
        assert s.qdrant_collection_name == "documents"

    def test_upload_defaults(self):
        s = _clean_settings()
        assert s.max_upload_size_mb == 50
        assert ".pdf" in s.allowed_extensions

    def test_api_defaults(self):
        s = _clean_settings()
        assert s.api_port == 8000
        assert s.api_host == "0.0.0.0"
        assert "http://localhost:3000" in s.cors_origins
        assert s.log_level == "info"

    def test_rag_defaults(self):
        s = _clean_settings()
        assert s.rag_chunk_size == 1000
        assert s.rag_chunk_overlap == 200
        assert s.rag_top_k == 5
        assert s.rag_score_threshold == 0.4

    def test_laya_rag_checks_are_disabled_by_default(self):
        s = _clean_settings()
        assert s.laya_model == "laya:latest"
        assert s.laya_rag_evidence_mode == "off"
        assert s.laya_rag_rewrite_mode == "off"
        assert s.laya_request_timeout_ms == 250

    def test_sql_agent_defaults(self):
        s = _clean_settings()
        assert s.sql_max_rows == 100
        assert s.sql_allow_writes is False

    def test_rate_limit_defaults(self):
        s = _clean_settings()
        assert s.rate_limit_default == "60/minute"
        assert s.rate_limit_llm == "10/minute"
        assert s.rate_limit_embedding == "20/minute"
        assert s.rate_limit_upload == "20/minute"


# =============================================================================
# Computed properties
# =============================================================================


class TestComputedProperties:
    """Test @property methods."""

    def test_max_upload_size_bytes(self):
        s = Settings()
        assert s.max_upload_size_bytes == s.max_upload_size_mb * 1024 * 1024

    def test_max_upload_size_bytes_custom(self):
        s = _clean_settings(max_upload_size_mb=100)
        assert s.max_upload_size_bytes == 100 * 1024 * 1024

    def test_allowed_extensions_set(self):
        s = Settings()
        exts = s.allowed_extensions_set
        assert isinstance(exts, set)
        assert ".pdf" in exts
        assert ".docx" in exts
        assert ".png" in exts
        assert ".csv" in exts

    def test_upload_path_creates_directory(self, tmp_path):
        s = Settings(upload_dir=str(tmp_path / "uploads"))
        path = s.upload_path
        assert isinstance(path, Path)
        assert path.exists()


# =============================================================================
# Validators
# =============================================================================


class TestValidators:
    """Test field validators."""

    def test_cors_origins_from_list(self):
        s = Settings(cors_origins=["http://a.com", "http://b.com"])
        assert s.cors_origins == ["http://a.com", "http://b.com"]

    def test_cors_origins_from_comma_string(self):
        s = Settings(cors_origins="http://a.com,http://b.com")
        assert s.cors_origins == ["http://a.com", "http://b.com"]

    def test_cors_origins_from_json_array(self):
        s = Settings(cors_origins='["http://a.com", "http://b.com"]')
        assert s.cors_origins == ["http://a.com", "http://b.com"]

    def test_cors_origins_strips_whitespace(self):
        s = Settings(cors_origins=" http://a.com , http://b.com ")
        assert "http://a.com" in s.cors_origins
        assert "http://b.com" in s.cors_origins

    def test_log_level_valid(self):
        for level in ("debug", "info", "warning", "error", "critical"):
            s = Settings(log_level=level)
            assert s.log_level == level

    def test_log_level_uppercased_normalized(self):
        s = Settings(log_level="DEBUG")
        assert s.log_level == "debug"

    def test_log_level_invalid_raises(self):
        with pytest.raises(Exception):  # pydantic ValidationError
            Settings(log_level="verbose")


# =============================================================================
# Environment variable overrides
# =============================================================================


class TestEnvOverrides:
    """Verify environment variables override defaults."""

    def test_env_override_port(self):
        with patch.dict(os.environ, {"API_PORT": "9999"}):
            s = Settings(_env_file=None)
            assert s.api_port == 9999

    def test_env_override_chat_model(self):
        with patch.dict(os.environ, {"OLLAMA_CHAT_MODEL": "mistral:7b"}):
            s = Settings(_env_file=None)
            assert s.ollama_chat_model == "mistral:7b"

    def test_env_override_rate_limit(self):
        with patch.dict(os.environ, {"RATE_LIMIT_LLM": "5/minute"}):
            s = Settings(_env_file=None)
            assert s.rate_limit_llm == "5/minute"

    def test_extra_env_vars_ignored(self):
        """Settings has extra='ignore', so unknown vars shouldn't cause errors."""
        with patch.dict(os.environ, {"COMPLETELY_UNKNOWN_VAR": "test"}):
            s = Settings()
            assert not hasattr(s, "completely_unknown_var")


# =============================================================================
# Module-level singleton
# =============================================================================


class TestSingleton:
    def test_module_level_settings(self):
        from app.config import settings

        assert isinstance(settings, Settings)
