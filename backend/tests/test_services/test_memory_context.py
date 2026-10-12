"""Tests for opt-in, bounded account memory context loading."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import LEGACY_ACCOUNT_ID, Account, Memory
from app.services.memory_context import MAX_MEMORY_CONTEXT_CHARS, load_account_memory_context


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
