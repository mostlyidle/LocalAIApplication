"""FastAPI application factory with lifespan management."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from fastapi import FastAPI

from app.api.middleware.cors import setup_cors
from app.api.middleware.error_handler import register_exception_handlers
from app.api.middleware.rate_limiting import setup_rate_limiting
from app.api.middleware.request_logging import setup_request_logging
from app.config import settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _configure_logging() -> None:
    """Set up structlog with stdlib integration."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup and shutdown logic."""
    logger = structlog.get_logger("lifespan")

    # ── Startup ─────────────────────────────────────────────────────
    logger.info("starting_up", port=settings.api_port)

    from app.agents.registry import AgentRegistry
    from app.prompt_store import PromptStore
    from app.services.comfyui import ComfyUIClient
    from app.services.market_data import FinnhubMarketDataClient
    from app.services.task_runner import TaskRunner

    profile_dir = Path(__file__).parent / "prompts"
    prompts = PromptStore(profile_dir)
    app.state.agent_registry = AgentRegistry(profile_dir, prompts)
    app.state.market_data = FinnhubMarketDataClient(
        api_key=settings.finnhub_api_key,
        cache_seconds=settings.market_data_cache_seconds,
    )
    app.state.comfyui = ComfyUIClient(settings.comfyui_url)
    app.state.task_runner = TaskRunner(
        app.state.agent_registry,
        prompts,
        market_data=app.state.market_data,
        comfyui=app.state.comfyui,
    )

    # Ensure data directories exist
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.chroma_persist_dir).mkdir(parents=True, exist_ok=True)

    # Initialize the application database tables (creates if not exist)
    from app.services.database import init_app_db
    from app.services.meetings import meeting_service

    await init_app_db()
    logger.info("database_initialized")

    reconciled_meetings = await meeting_service.reconcile_active_meetings()
    logger.info("meeting_startup_reconciliation_complete", count=reconciled_meetings)

    # Discover external MCP tools (non-blocking, failures are logged)
    from app.mcp.client import mcp_client

    try:
        tools = await mcp_client.discover_tools()
        if tools:
            logger.info("mcp_tools_available", count=len(tools))
    except Exception as exc:
        logger.warning("mcp_discovery_failed", error=str(exc))

    yield

    # ── Shutdown ────────────────────────────────────────────────────
    from app.services.database import close_all_sql_engines, close_app_db
    from app.services.hybrid_vector_store import hybrid_vector_store_service

    await mcp_client.close()
    await app.state.market_data.close()
    await app.state.comfyui.close()
    await hybrid_vector_store_service.close()
    await close_all_sql_engines()
    await close_app_db()
    logger.info("shutdown_complete")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    _configure_logging()

    app = FastAPI(
        title="Local AI Application",
        description=(
            "A fully local, production-grade AI application with document intelligence, "
            "SQL agent, RAG, and MCP integration. Powered by Ollama on Apple Silicon."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # Middleware (order matters: outermost → innermost)
    setup_cors(app)
    setup_request_logging(app)
    setup_rate_limiting(app)

    # Exception handlers
    register_exception_handlers(app)

    # API routes
    from app.api.routes import agents, chat, documents, meetings, rag, sql, tasks, tools

    app.include_router(agents.router, prefix="/api/v1", tags=["Agents"])
    app.include_router(chat.router, prefix="/api/v1", tags=["Chat"])
    app.include_router(documents.router, prefix="/api/v1", tags=["Documents"])
    app.include_router(sql.router, prefix="/api/v1", tags=["SQL"])
    app.include_router(rag.router, prefix="/api/v1", tags=["RAG"])
    app.include_router(tasks.router, prefix="/api/v1", tags=["Agents"])
    app.include_router(tools.router, prefix="/api/v1", tags=["Tools"])
    app.include_router(meetings.router, prefix="/api/v1", tags=["Meetings"])

    return app


# Uvicorn entry point
app = create_app()
