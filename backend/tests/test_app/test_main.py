"""Tests for the FastAPI application factory in app.main."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def lifespan_app_session_factory(
    async_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Return an initialized fixture DB for lifespan configuration reads."""
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


class TestCreateApp:
    """Tests for create_app() factory function."""

    def test_returns_fastapi_instance(self):
        """create_app should return a FastAPI application."""
        from app.main import create_app

        app = create_app()
        assert isinstance(app, FastAPI)

    def test_app_title(self):
        """App should have the correct title."""
        from app.main import create_app

        app = create_app()
        assert app.title == "Local AI Application"

    def test_app_version(self):
        """App should have version 0.1.0."""
        from app.main import create_app

        app = create_app()
        assert app.version == "0.1.0"

    def test_routes_registered(self):
        """App should have routes for all API endpoints."""
        from app.main import create_app

        app = create_app()
        route_paths = {r.path for r in app.routes if hasattr(r, "path")}

        # Check that all expected route prefixes are present
        assert "/api/v1/chat" in route_paths
        assert "/api/v1/agents" in route_paths
        assert "/api/v1/tools" in route_paths
        assert "/api/v1/health" in route_paths
        assert "/api/v1/sql/query" in route_paths
        assert "/api/v1/rag/search" in route_paths
        assert "/api/v1/meetings/{meeting_id}/stream" in route_paths
        assert "/api/v1/meetings/{meeting_id}/audio" not in route_paths
        assert "/api/v1/meetings/{meeting_id}/ws" not in route_paths

    def test_has_lifespan(self):
        """App should have a lifespan handler configured."""
        from app.main import create_app

        app = create_app()
        # FastAPI stores lifespan in router
        assert app.router.lifespan_context is not None


class TestLifespan:
    """Tests for the lifespan context manager."""

    async def test_lifespan_creates_directories(
        self,
        tmp_path: Path,
        lifespan_app_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Lifespan startup should create data directories."""
        upload_dir = tmp_path / "uploads"
        chroma_dir = tmp_path / "chroma"

        with (
            patch("app.main.settings") as mock_settings,
            patch("app.services.database.init_app_db", new_callable=AsyncMock),
            patch(
                "app.services.database.get_app_session_factory",
                return_value=lifespan_app_session_factory,
            ),
            patch(
                "app.services.meetings.meeting_service.reconcile_active_meetings",
                new_callable=AsyncMock,
            ),
            patch("app.services.database.close_all_sql_engines", new_callable=AsyncMock),
            patch("app.services.database.close_app_db", new_callable=AsyncMock),
        ):
            mock_settings.upload_dir = str(upload_dir)
            mock_settings.chroma_persist_dir = str(chroma_dir)
            mock_settings.api_port = 8000
            mock_settings.log_level = "warning"
            mock_settings.finnhub_api_key = None
            mock_settings.market_data_cache_seconds = 60
            mock_settings.comfyui_url = "http://localhost:8188"
            mock_settings.ollama_base_url = "http://localhost:11434"
            mock_settings.laya_model = "laya:latest"
            mock_settings.laya_request_timeout_ms = 250
            mock_settings.laya_rag_evidence_mode = "off"
            mock_settings.laya_rag_rewrite_mode = "off"

            from app.main import lifespan

            fake_app = FastAPI()
            async with lifespan(fake_app):
                assert upload_dir.exists()
                assert chroma_dir.exists()

    async def test_lifespan_initializes_db(
        self,
        tmp_path: Path,
        lifespan_app_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Lifespan should call init_app_db on startup."""
        mock_init = AsyncMock()

        with (
            patch("app.main.settings") as mock_settings,
            patch("app.services.database.init_app_db", mock_init),
            patch(
                "app.services.database.get_app_session_factory",
                return_value=lifespan_app_session_factory,
            ),
            patch(
                "app.services.meetings.meeting_service.reconcile_active_meetings",
                new_callable=AsyncMock,
            ),
            patch("app.services.database.close_all_sql_engines", new_callable=AsyncMock),
            patch("app.services.database.close_app_db", new_callable=AsyncMock),
        ):
            mock_settings.upload_dir = str(tmp_path / "uploads")
            mock_settings.chroma_persist_dir = str(tmp_path / "chroma")
            mock_settings.api_port = 8000
            mock_settings.log_level = "warning"
            mock_settings.finnhub_api_key = None
            mock_settings.market_data_cache_seconds = 60
            mock_settings.comfyui_url = "http://localhost:8188"
            mock_settings.ollama_base_url = "http://localhost:11434"
            mock_settings.laya_model = "laya:latest"
            mock_settings.laya_request_timeout_ms = 250
            mock_settings.laya_rag_evidence_mode = "off"
            mock_settings.laya_rag_rewrite_mode = "off"

            from app.main import lifespan

            fake_app = FastAPI()
            async with lifespan(fake_app):
                mock_init.assert_awaited_once()

    async def test_lifespan_reconciles_interrupted_meetings(
        self,
        tmp_path: Path,
        lifespan_app_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Lifespan should reconcile persisted active meetings after DB initialization."""
        mock_init = AsyncMock()
        mock_reconcile = AsyncMock(return_value=2)

        with (
            patch("app.main.settings") as mock_settings,
            patch("app.services.database.init_app_db", mock_init),
            patch(
                "app.services.database.get_app_session_factory",
                return_value=lifespan_app_session_factory,
            ),
            patch(
                "app.services.meetings.meeting_service.reconcile_active_meetings",
                mock_reconcile,
            ),
            patch("app.services.database.close_all_sql_engines", new_callable=AsyncMock),
            patch("app.services.database.close_app_db", new_callable=AsyncMock),
        ):
            mock_settings.upload_dir = str(tmp_path / "uploads")
            mock_settings.chroma_persist_dir = str(tmp_path / "chroma")
            mock_settings.api_port = 8000
            mock_settings.log_level = "warning"
            mock_settings.finnhub_api_key = None
            mock_settings.market_data_cache_seconds = 60
            mock_settings.comfyui_url = "http://localhost:8188"
            mock_settings.ollama_base_url = "http://localhost:11434"
            mock_settings.laya_model = "laya:latest"
            mock_settings.laya_request_timeout_ms = 250
            mock_settings.laya_rag_evidence_mode = "off"
            mock_settings.laya_rag_rewrite_mode = "off"

            from app.main import lifespan

            fake_app = FastAPI()
            async with lifespan(fake_app):
                mock_init.assert_awaited_once()
                mock_reconcile.assert_awaited_once_with()

    async def test_lifespan_closes_db_on_shutdown(
        self,
        tmp_path: Path,
        lifespan_app_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Lifespan should close DB connections on shutdown."""
        mock_close_sql = AsyncMock()
        mock_close_app = AsyncMock()
        mock_recall_worker = AsyncMock()

        with (
            patch("app.main.settings") as mock_settings,
            patch("app.services.database.init_app_db", new_callable=AsyncMock),
            patch(
                "app.services.database.get_app_session_factory",
                return_value=lifespan_app_session_factory,
            ),
            patch(
                "app.services.meetings.meeting_service.reconcile_active_meetings",
                new_callable=AsyncMock,
            ),
            patch("app.services.memory_recall_worker.run_recall_worker", mock_recall_worker),
            patch("app.services.database.close_all_sql_engines", mock_close_sql),
            patch("app.services.database.close_app_db", mock_close_app),
        ):
            mock_settings.upload_dir = str(tmp_path / "uploads")
            mock_settings.chroma_persist_dir = str(tmp_path / "chroma")
            mock_settings.api_port = 8000
            mock_settings.log_level = "warning"
            mock_settings.finnhub_api_key = None
            mock_settings.market_data_cache_seconds = 60
            mock_settings.comfyui_url = "http://localhost:8188"
            mock_settings.ollama_base_url = "http://localhost:11434"
            mock_settings.laya_model = "laya:latest"
            mock_settings.laya_request_timeout_ms = 250
            mock_settings.laya_rag_evidence_mode = "off"
            mock_settings.laya_rag_rewrite_mode = "off"

            from app.main import lifespan

            fake_app = FastAPI()
            async with lifespan(fake_app):
                pass
            # After context manager exits, shutdown should have run
            mock_close_sql.assert_awaited_once()
            mock_close_app.assert_awaited_once()
            mock_recall_worker.assert_awaited_once()
            assert mock_recall_worker.await_args.args[0].is_set()


class TestConfigureLogging:
    """Tests for _configure_logging helper."""

    def test_configure_logging_does_not_raise(self):
        """_configure_logging should complete without errors."""
        from app.main import _configure_logging

        # Should not raise
        _configure_logging()

    def test_structlog_configured(self):
        """After calling _configure_logging, structlog should be usable."""
        from app.main import _configure_logging

        _configure_logging()
        import structlog

        logger = structlog.get_logger("test")
        assert logger is not None


class TestModuleLevelApp:
    """Tests for the module-level `app` variable."""

    def test_module_app_is_fastapi(self):
        """The module-level `app` should be a FastAPI instance."""
        from app.main import app

        assert isinstance(app, FastAPI)
