"""Tests for app.services.database."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.models.db_models import Base, Conversation, Document, LEGACY_ACCOUNT_ID, Meeting
from app.services.database import _enable_sqlite_wal


# =============================================================================
# Test the in-memory database from conftest fixtures
# =============================================================================


class TestDatabaseFixtures:
    """Verify the test fixtures themselves work correctly."""

    async def test_engine_is_async(self, async_engine: AsyncEngine):
        assert isinstance(async_engine, AsyncEngine)

    async def test_session_works(self, db_session: AsyncSession):
        result = await db_session.execute(text("SELECT 1"))
        assert result.scalar() == 1

    async def test_sqlite_connections_enable_foreign_keys(self):
        engine = create_async_engine("sqlite+aiosqlite://")
        _enable_sqlite_wal(engine)
        try:
            async with engine.connect() as connection:
                result = await connection.execute(text("PRAGMA foreign_keys"))
            assert result.scalar_one() == 1
        finally:
            await engine.dispose()

    @pytest.mark.parametrize(
        "record_factory",
        [
            lambda: Conversation(title="Missing owner"),
            lambda: Document(
                filename="missing.txt",
                format="txt",
                size_bytes=0,
                storage_path="/tmp/missing.txt",
            ),
            lambda: Meeting(
                consent_policy_version="v1",
                consent_attested_at=datetime.now(UTC),
            ),
        ],
    )
    async def test_private_records_require_an_explicit_owner(self, db_session, record_factory):
        db_session.add(record_factory())
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_tables_created(self, db_session: AsyncSession):
        """Verify that all ORM tables exist in the test database."""
        result = await db_session.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        table_names = {row[0] for row in result.fetchall()}
        assert "conversations" in table_names
        assert "messages" in table_names
        assert "tool_calls" in table_names
        assert "documents" in table_names
        assert "meetings" in table_names
        assert "transcript_segments" in table_names
        assert "detected_questions" in table_names


# =============================================================================
# CRUD on ORM models
# =============================================================================


class TestConversationCRUD:
    """Test basic ORM operations via the async session."""

    async def test_create_conversation(self, db_session: AsyncSession):
        conv = Conversation(owner_id=LEGACY_ACCOUNT_ID, title="Test Chat")
        db_session.add(conv)
        await db_session.flush()

        assert conv.id is not None
        assert conv.title == "Test Chat"
        assert conv.created_at is not None

    async def test_create_and_read_conversation(self, db_session: AsyncSession):
        conv = Conversation(owner_id=LEGACY_ACCOUNT_ID, title="Read Test")
        db_session.add(conv)
        await db_session.flush()

        from sqlalchemy import select

        stmt = select(Conversation).where(Conversation.id == conv.id)
        result = await db_session.execute(stmt)
        fetched = result.scalar_one()
        assert fetched.title == "Read Test"


class TestDocumentCRUD:
    """Test Document model CRUD."""

    async def test_create_document(self, db_session: AsyncSession):
        doc = Document(
            owner_id=LEGACY_ACCOUNT_ID,
            filename="test.pdf",
            format="pdf",
            size_bytes=1024,
            storage_path="/tmp/test.pdf",
            status="pending",
        )
        db_session.add(doc)
        await db_session.flush()

        assert doc.id is not None
        assert doc.filename == "test.pdf"
        assert doc.size_bytes == 1024


# =============================================================================
# Database module functions
# =============================================================================


class TestDatabaseModule:
    """Test the database.py module-level functions with isolation."""

    def test_unknown_connection_does_not_fall_back_to_default(self):
        from app.api.middleware.error_handler import DatabaseConnectionError
        from app.services.database import get_sql_engine

        with pytest.raises(DatabaseConnectionError, match="not registered"):
            get_sql_engine(name="unregistered-connection")

    async def test_get_sql_engine_caching(self):
        """Verify get_sql_engine caches engines by name."""
        from app.services.database import _sql_engines, get_sql_engine

        # Clear existing engines to isolate
        original = dict(_sql_engines)
        _sql_engines.clear()

        try:
            engine1 = get_sql_engine(database_url="sqlite+aiosqlite://", name="test_cache")
            engine2 = get_sql_engine(name="test_cache")
            assert engine1 is engine2
        finally:
            # Cleanup: dispose and restore
            if "test_cache" in _sql_engines:
                await _sql_engines["test_cache"].dispose()
                del _sql_engines["test_cache"]
            _sql_engines.update(original)

    async def test_close_all_sql_engines(self):
        """Verify close_all_sql_engines disposes and clears the cache."""
        from app.services.database import (
            _sql_engines,
            close_all_sql_engines,
            get_sql_engine,
        )

        original = dict(_sql_engines)
        _sql_engines.clear()

        try:
            get_sql_engine(database_url="sqlite+aiosqlite://", name="disposable")
            assert "disposable" in _sql_engines
            await close_all_sql_engines()
            assert len(_sql_engines) == 0
        finally:
            _sql_engines.update(original)
