"""SQLAlchemy async engine and session management for both app and target databases."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import structlog
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.models.db_models import Base

logger = structlog.get_logger(__name__)


def _enable_sqlite_wal(engine: AsyncEngine) -> None:
    """Enable WAL journal mode on SQLite connections for concurrent access.

    WAL (Write-Ahead Logging) allows concurrent readers while a write is
    in progress, which prevents the 'database is locked' errors common
    with aiosqlite under concurrent async requests.
    """
    sync_engine = engine.sync_engine

    @event.listens_for(sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn: object, _connection_record: object) -> None:
        cursor = dbapi_conn.cursor()  # type: ignore[union-attr]
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


# ── Application database (chat history, document metadata) ──────────────

_app_engine: AsyncEngine | None = None
_app_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_app_engine() -> AsyncEngine:
    """Get or create the application database engine."""
    global _app_engine
    if _app_engine is None:
        _app_engine = create_async_engine(
            settings.app_database_url,
            echo=False,
            pool_pre_ping=True,
            connect_args={"timeout": 30},
        )
        _enable_sqlite_wal(_app_engine)
    return _app_engine


def get_app_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the application session factory."""
    global _app_session_factory
    if _app_session_factory is None:
        _app_session_factory = async_sessionmaker(
            get_app_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _app_session_factory


async def get_app_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session for the application database.

    Intended for use as a FastAPI dependency.
    """
    factory = get_app_session_factory()
    async with factory() as session:
        yield session


async def init_app_db() -> None:
    """Create all application database tables if they don't exist."""
    engine = get_app_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("app_db_initialized", url=settings.app_database_url)


async def close_app_db() -> None:
    """Dispose the application database engine on shutdown."""
    global _app_engine, _app_session_factory
    if _app_engine is not None:
        await _app_engine.dispose()
        _app_engine = None
        _app_session_factory = None
        logger.info("app_db_closed")


# ── Target database (for SQL Agent queries) ────────────────────────────

_sql_engines: dict[str, AsyncEngine] = {}


def get_sql_engine(database_url: str | None = None, name: str = "default") -> AsyncEngine:
    """Get or create an engine for a target SQL database.

    Args:
        database_url: The database URL. Falls back to settings.sql_database_url.
        name: A logical name for this connection (for caching).

    Returns:
        An async SQLAlchemy engine.
    """
    if name in _sql_engines:
        return _sql_engines[name]

    url = database_url or settings.sql_database_url
    connect_kwargs = {"timeout": 30} if "sqlite" in url else {}
    engine = create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        connect_args=connect_kwargs,
    )
    if "sqlite" in url:
        _enable_sqlite_wal(engine)
    _sql_engines[name] = engine
    logger.info("sql_engine_created", name=name, url=url.split("@")[-1])  # strip creds
    return engine


async def get_sql_session(name: str = "default") -> AsyncSession:
    """Create a one-off async session for executing SQL agent queries."""
    engine = get_sql_engine(name=name)
    return AsyncSession(engine, expire_on_commit=False)


async def close_all_sql_engines() -> None:
    """Dispose all target SQL engines."""
    for name, engine in _sql_engines.items():
        await engine.dispose()
        logger.info("sql_engine_closed", name=name)
    _sql_engines.clear()
