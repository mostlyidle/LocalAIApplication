"""Tests for opt-in, bounded account memory context loading."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import LEGACY_ACCOUNT_ID, Account, Memory
from app.services.memory_context import (
    MAX_MEMORY_CONTEXT_CHARS,
    load_account_memory_context,
    memory_sources_from_context,
)


async def test_memory_context_is_empty_until_account_opts_in(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            Account(
                id=LEGACY_ACCOUNT_ID,
                username="memory-context-test",
                display_name="Memory Context Test",
                password_hash="!test!",
            ),
            Memory(owner_id=LEGACY_ACCOUNT_ID, kind="fact", content="Lives in Toronto"),
        ]
    )
    await db_session.commit()

    assert await load_account_memory_context(LEGACY_ACCOUNT_ID, db=db_session) == ""


def test_memory_sources_include_only_bounded_past_conversation_labels() -> None:
    context = json.dumps(
        [
            {"type": "preference", "content": "Concise"},
            {"type": "past_conversation", "conversation_id": "chat-1", "title": "First"},
            {"type": "past_conversation", "conversation_id": "chat-1", "title": "Duplicate"},
            {"type": "past_conversation", "conversation_id": "chat-2", "content": "summary"},
        ]
    )

    assert memory_sources_from_context(context) == [
        {"conversation_id": "chat-1", "title": "First"},
        {"conversation_id": "chat-2", "title": "Past conversation"},
    ]


async def test_memory_context_is_owned_approved_active_and_bounded(
    db_session: AsyncSession,
) -> None:
    other_owner = "other-memory-owner"
    db_session.add_all(
        [
            Account(
                id=LEGACY_ACCOUNT_ID,
                username="memory-context-enabled",
                display_name="Enabled Account",
                password_hash="!test!",
                memory_enabled=True,
            ),
            Account(
                id=other_owner,
                username="memory-context-other",
                display_name="Other Account",
                password_hash="!test!",
                memory_enabled=True,
            ),
            Memory(owner_id=LEGACY_ACCOUNT_ID, kind="preference", content="Concise answers"),
            Memory(owner_id=LEGACY_ACCOUNT_ID, kind="fact", content="Unapproved", approved=False),
            Memory(
                owner_id=LEGACY_ACCOUNT_ID,
                kind="fact",
                content="Expired",
                expires_at=datetime.now(UTC) - timedelta(days=1),
            ),
            Memory(
                owner_id=LEGACY_ACCOUNT_ID,
                kind="fact",
                content="Deleted",
                deleted_at=datetime.now(UTC),
            ),
            Memory(owner_id=other_owner, kind="fact", content="Private to another account"),
        ]
    )
    await db_session.commit()

    context = await load_account_memory_context(LEGACY_ACCOUNT_ID, db=db_session)
    assert "Concise answers" in context
    assert "Unapproved" not in context
    assert "Expired" not in context
    assert "Deleted" not in context
    assert "Private to another account" not in context

    long_memories = [
        Memory(owner_id=LEGACY_ACCOUNT_ID, kind="fact", content=f"{index}: {'x' * 800}")
        for index in range(10)
    ]
    db_session.add_all(long_memories)
    await db_session.commit()
    context = await load_account_memory_context(LEGACY_ACCOUNT_ID, db=db_session)
    assert len(context) <= MAX_MEMORY_CONTEXT_CHARS
    assert len(json.loads(context)) < 11


async def test_memory_database_failure_does_not_block_chat() -> None:
    with patch(
        "app.services.database.get_app_session_factory", side_effect=RuntimeError("offline")
    ):
        assert await load_account_memory_context(LEGACY_ACCOUNT_ID) == ""


async def test_memory_context_includes_relevant_past_chat_only_when_enabled(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        Account(
            id=LEGACY_ACCOUNT_ID,
            username="past-chat-memory-context",
            display_name="Past Chat Context",
            password_hash="!test!",
            memory_enabled=True,
            past_chat_recall_enabled=True,
            memory_epoch=4,
        )
    )
    await db_session.commit()
    search = AsyncMock(
        return_value=[
            {
                "type": "past_conversation",
                "conversation_id": "older-chat",
                "title": "Prior decision",
                "content": "The user chose PostgreSQL for this project.",
            }
        ]
    )

    with patch("app.services.memory_vector_index.memory_vector_index.search_summaries", search):
        context = await load_account_memory_context(
            LEGACY_ACCOUNT_ID,
            query="Which database did I choose?",
            exclude_conversation_id="current-chat",
            db=db_session,
        )

    assert "PostgreSQL" in context
    search.assert_awaited_once_with(
        db_session,
        owner_id=LEGACY_ACCOUNT_ID,
        memory_epoch=4,
        query="Which database did I choose?",
        exclude_conversation_id="current-chat",
        limit=4,
    )


async def test_past_chat_recall_does_not_require_explicit_memory_opt_in(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        Account(
            id=LEGACY_ACCOUNT_ID,
            username="independent-past-chat-memory",
            display_name="Independent Past Chat",
            password_hash="!test!",
            memory_enabled=False,
            past_chat_recall_enabled=True,
            memory_epoch=1,
        )
    )
    await db_session.commit()
    search = AsyncMock(
        return_value=[
            {
                "type": "past_conversation",
                "conversation_id": "older-chat",
                "title": "Prior decision",
                "content": "The user chose PostgreSQL.",
            }
        ]
    )
    with patch("app.services.memory_vector_index.memory_vector_index.search_summaries", search):
        context = await load_account_memory_context(
            LEGACY_ACCOUNT_ID, query="Which database?", db=db_session
        )

    assert "PostgreSQL" in context
    search.assert_awaited_once()
