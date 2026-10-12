"""Queue durable indexing work for opted-in, eligible conversation turns."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models.db_models import Account, Conversation, MemoryOutboxJob

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def enqueue_conversation_recall(
    db: AsyncSession,
    *,
    owner_id: str,
    conversation: Conversation,
    source_message_id: str,
) -> bool:
    """Add one turn to the outbox when both account and conversation permit it.

    The caller commits this row with its chat messages. A future worker must
    repeat the eligibility check before reading or indexing source content.
    """
    if conversation.owner_id != owner_id or conversation.exclude_from_memory:
        return False

    account = await db.scalar(select(Account).where(Account.id == owner_id))
    if account is None or not account.is_enabled or not account.past_chat_recall_enabled:
        return False

    existing = await db.scalar(
        select(MemoryOutboxJob.id).where(MemoryOutboxJob.source_message_id == source_message_id)
    )
    if existing is not None:
        return False

    db.add(
        MemoryOutboxJob(
            owner_id=owner_id,
            conversation_id=conversation.id,
            source_message_id=source_message_id,
            memory_epoch=account.memory_epoch,
            status="pending",
            available_at=datetime.now(UTC),
        )
    )
    return True
