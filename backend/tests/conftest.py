"""Shared fixtures for the test suite.

Provides:
    - An in-memory async SQLite database with the app schema.
    - A FastAPI test client (httpx.AsyncClient) with dependency overrides.
    - Helper fixtures for seeding test data.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ---------------------------------------------------------------------------
# Ensure settings use test-friendly values BEFORE importing app modules.
# Must happen before any import of app.config triggers Settings().
# ---------------------------------------------------------------------------
os.environ.setdefault("APP_DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("SQL_DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("UPLOAD_DIR", "/tmp/test_uploads")
os.environ.setdefault("LOG_LEVEL", "warning")

# Rate limits — set very high so tests never hit real limits.
os.environ.setdefault("RATE_LIMIT_DEFAULT", "1000/minute")
os.environ.setdefault("RATE_LIMIT_LLM", "1000/minute")
os.environ.setdefault("RATE_LIMIT_EMBEDDING", "1000/minute")
os.environ.setdefault("RATE_LIMIT_UPLOAD", "1000/minute")


from app.models.db_models import LEGACY_ACCOUNT_ID, Account, AccountSession, Base
from app.services.auth import AuthenticatedSession

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


# =============================================================================
# Database fixtures
# =============================================================================


@pytest.fixture
async def async_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create an in-memory async SQLite engine with all tables."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(async_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session bound to the test engine."""
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


# =============================================================================
# FastAPI test client
# =============================================================================


@pytest.fixture
def authenticated_test_session() -> AuthenticatedSession:
    """Return an in-memory principal shared by authenticated API tests."""
    return AuthenticatedSession(
        account=Account(
            id=LEGACY_ACCOUNT_ID,
            username="test-account",
            display_name="Test Account",
            password_hash="!test!",
        ),
        session=AccountSession(
            id="test-session",
            account_id=LEGACY_ACCOUNT_ID,
            token_hash="0" * 64,
            csrf_token="test-csrf-token",
            expires_at=datetime.now(UTC),
        ),
    )


@pytest.fixture
async def app(async_engine: AsyncEngine, authenticated_test_session: AuthenticatedSession):
    """Create a FastAPI app with dependency overrides for testing."""
    from app.agents.registry import AgentRegistry
    from app.main import create_app
    from app.prompt_store import PromptStore

    test_app = create_app()
    profile_dir = Path(__file__).resolve().parents[1] / "app" / "prompts"
    test_app.state.agent_registry = AgentRegistry(profile_dir, PromptStore(profile_dir))

    # Override the database dependency to use our test session
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    from app.dependencies import get_authenticated_session, get_db, get_websocket_session

    test_app.dependency_overrides[get_db] = _override_get_db
    test_app.dependency_overrides[get_authenticated_session] = lambda: authenticated_test_session
    test_app.dependency_overrides[get_websocket_session] = lambda: authenticated_test_session

    return test_app


@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """Provide an httpx.AsyncClient wired to the test FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# =============================================================================
# Target SQL database (for SQL tools / routes)
# =============================================================================


@pytest.fixture
async def sql_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create a separate in-memory SQLite database for SQL-tool tests.

    Pre-populated with a simple schema: a 'users' table.
    """
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: sync_conn.execute(
                __import__("sqlalchemy").text(
                    """
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        email TEXT UNIQUE NOT NULL,
                        age INTEGER
                    )
                    """
                )
            )
        )
        await conn.run_sync(
            lambda sync_conn: sync_conn.execute(
                __import__("sqlalchemy").text(
                    """
                    INSERT INTO users (name, email, age) VALUES
                    ('Alice', 'alice@test.com', 30),
                    ('Bob', 'bob@test.com', 25),
                    ('Charlie', 'charlie@test.com', 35)
                    """
                )
            )
        )

    yield engine
    await engine.dispose()


# =============================================================================
# Mock LLM
# =============================================================================


@pytest.fixture
def mock_llm() -> MagicMock:
    """Create a mock LLM that returns a canned response.

    Override ``mock_llm.ainvoke.return_value`` in individual tests
    to customise the response content.
    """
    llm = MagicMock()
    response = MagicMock()
    response.content = '{"agent": "chat"}'
    llm.ainvoke = AsyncMock(return_value=response)
    return llm


@pytest.fixture
def golden_envelope() -> bytes:
    """Read the desktop-owned shared meeting envelope fixture."""
    path = Path(__file__).resolve().parents[2] / "meeting-contract" / "golden_envelope.hex"
    if not path.exists():
        pytest.skip("desktop golden envelope is not available in this checkout")
    return bytes.fromhex(path.read_text(encoding="utf-8").strip())


# =============================================================================
# Temp paths
# =============================================================================


@pytest.fixture(autouse=True)
def _ensure_tmp_dirs() -> None:
    """Ensure temporary test directories exist."""
    Path("/tmp/test_uploads").mkdir(parents=True, exist_ok=True)
