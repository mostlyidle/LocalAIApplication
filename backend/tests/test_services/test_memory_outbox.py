"""Tests for opt-in and per-conversation recall job eligibility."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import Account, Conversation, MemoryOutboxJob, Message
from app.services.memory_outbox import enqueue_conversation_recall


@pytest.mark.asyncio
async def test_enqueue_only_for_opted_in_eligible_conversation(db_session: AsyncSession) -> None:
    account = Account(
        id="recall-account",
        username="recall-account",
        display_name="Recall Account",
        password_hash="!test!",
        past_chat_recall_enabled=True,
        memory_epoch=3,
    )
    eligible = Conversation(id="eligible-chat", owner_id=account.id)
    excluded = Conversation(id="excluded-chat", owner_id=account.id, exclude_from_memory=True)
    db_session.add_all(
        [
            account,
            eligible,
            excluded,
            Message(
                id="turn-assistant-message",
                conversation_id=eligible.id,
                role="assistant",
                content="reply",
            ),
            Message(
                id="excluded-assistant-message",
                conversation_id=excluded.id,
                role="assistant",
                content="reply",
            ),
        ]
    )
    await db_session.flush()

    queued = await enqueue_conversation_recall(
        db_session,
        owner_id=account.id,
        conversation=eligible,
        source_message_id="turn-assistant-message",
    )
    duplicate_queued = await enqueue_conversation_recall(
        db_session,
        owner_id=account.id,
        conversation=eligible,
        source_message_id="turn-assistant-message",
    )
    excluded_queued = await enqueue_conversation_recall(
        db_session,
        owner_id=account.id,
        conversation=excluded,
        source_message_id="excluded-assistant-message",
    )
    await db_session.flush()

    jobs = list((await db_session.scalars(select(MemoryOutboxJob))).all())
    assert queued is True
    assert duplicate_queued is False
    assert excluded_queued is False
    assert len(jobs) == 1
    assert jobs[0].owner_id == account.id
    assert jobs[0].conversation_id == eligible.id
    assert jobs[0].source_message_id == "turn-assistant-message"
    assert jobs[0].memory_epoch == 3
    assert jobs[0].status == "pending"


@pytest.mark.asyncio
async def test_enqueue_skips_when_account_has_not_opted_in(db_session: AsyncSession) -> None:
    account = Account(
        id="recall-disabled",
        username="recall-disabled",
        display_name="Recall Disabled",
        password_hash="!test!",
    )
    conversation = Conversation(id="recall-disabled-chat", owner_id=account.id)
    db_session.add_all(
        [
            account,
            conversation,
            Message(
                id="disabled-assistant-message",
                conversation_id=conversation.id,
                role="assistant",
                content="reply",
            ),
        ]
    )
    await db_session.flush()

    queued = await enqueue_conversation_recall(
        db_session,
        owner_id=account.id,
        conversation=conversation,
        source_message_id="disabled-assistant-message",
    )

    assert queued is False
    assert await db_session.scalar(select(MemoryOutboxJob.id)) is None


@pytest.mark.asyncio
async def test_enqueue_rejects_owner_mismatch(db_session: AsyncSession) -> None:
    account = Account(
        id="recall-owner",
        username="recall-owner",
        display_name="Recall Owner",
        password_hash="!test!",
        past_chat_recall_enabled=True,
    )
    conversation = Conversation(id="another-owners-chat", owner_id="different-owner")
    db_session.add(account)
    await db_session.flush()

    queued = await enqueue_conversation_recall(
        db_session,
        owner_id=account.id,
        conversation=conversation,
        source_message_id="foreign-assistant-message",
    )

    assert queued is False
