"""Tests for durable recall summary processing and consent revalidation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.db_models import (
    Account,
    Conversation,
    ConversationRecallSummary,
    MemoryOutboxJob,
    MemoryVectorCleanupJob,
    Message,
)
from app.services.memory_recall_worker import (
    process_one_recall_job,
    process_one_vector_cleanup_job,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_job(
    db: AsyncSession,
    *,
    epoch: int = 0,
    excluded: bool = False,
    transcript: str = "user: I prefer concise replies\nassistant: I will keep that in mind.",
) -> MemoryOutboxJob:
    account = Account(
        id="worker-account",
        username="worker-account",
        display_name="Worker Account",
        password_hash="!test!",
        past_chat_recall_enabled=True,
        memory_epoch=epoch,
    )
    conversation = Conversation(
        id="worker-conversation",
        owner_id=account.id,
        exclude_from_memory=excluded,
    )
    user_message = Message(
        id="worker-user-message",
        conversation_id=conversation.id,
        role="user",
        content=transcript.split("\n", maxsplit=1)[0].removeprefix("user: "),
        created_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    source = Message(
        id="worker-source-message",
        conversation_id=conversation.id,
        role="assistant",
        content=transcript.split("\n", maxsplit=1)[-1].removeprefix("assistant: "),
        created_at=datetime.now(UTC),
    )
    job = MemoryOutboxJob(
        id="worker-job",
        owner_id=account.id,
        conversation_id=conversation.id,
        source_message_id=source.id,
        memory_epoch=epoch,
        status="pending",
        available_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    db.add_all([account, conversation, user_message, source, job])
    await db.flush()
    return job


@pytest.mark.asyncio
async def test_worker_persists_bounded_summary_and_completes_job(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_job(db_session)
    summarize = AsyncMock(return_value="User prefers concise replies.")
    from app.services.memory_vector_index import memory_vector_index

    upsert_summary = AsyncMock(return_value=True)
    monkeypatch.setattr(memory_vector_index, "upsert_summary", upsert_summary)

    processed = await process_one_recall_job(db_session, summarize=summarize)

    job = await db_session.get(MemoryOutboxJob, "worker-job")
    summary = await db_session.scalar(select(ConversationRecallSummary))
    assert processed is True
    assert summarize.await_count == 1
    upsert_summary.assert_awaited_once()
    assert "user: I prefer concise replies" in summarize.await_args.args[0]
    assert job.status == "done"
    assert job.lease_until is None
    assert summary.owner_id == "worker-account"
    assert summary.conversation_id == "worker-conversation"
    assert summary.source_message_id == "worker-source-message"
    assert summary.memory_epoch == 0
    assert summary.content == "User prefers concise replies."


@pytest.mark.asyncio
async def test_worker_reclaims_expired_processing_lease(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = await _seed_job(db_session)
    job.status = "processing"
    job.attempts = 1
    job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    from app.services.memory_vector_index import memory_vector_index

    monkeypatch.setattr(memory_vector_index, "upsert_summary", AsyncMock(return_value=True))

    processed = await process_one_recall_job(
        db_session, summarize=AsyncMock(return_value="Recovered after restart.")
    )

    assert processed is True
    assert job.status == "done"
    assert job.attempts == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["epoch", "excluded", "disabled"])
async def test_worker_skips_jobs_that_fail_consent_revalidation(
    db_session: AsyncSession, case: str
) -> None:
    job = await _seed_job(db_session, epoch=0, excluded=case == "excluded")
    if case == "epoch":
        account = await db_session.get(Account, job.owner_id)
        account.memory_epoch = 1
    elif case == "disabled":
        account = await db_session.get(Account, job.owner_id)
        account.past_chat_recall_enabled = False
    summarize = AsyncMock(return_value="Must never be stored.")

    await process_one_recall_job(db_session, summarize=summarize)

    job = await db_session.get(MemoryOutboxJob, "worker-job")
    assert job.status == "skipped"
    assert summarize.await_count == 0
    assert await db_session.scalar(select(ConversationRecallSummary)) is None


@pytest.mark.asyncio
async def test_worker_filters_secret_like_transcript_before_inference(
    db_session: AsyncSession,
) -> None:
    await _seed_job(db_session, transcript="user: my api_key=secret-value")
    summarize = AsyncMock(return_value="A secret was discussed.")

    await process_one_recall_job(db_session, summarize=summarize)

    job = await db_session.get(MemoryOutboxJob, "worker-job")
    assert job.status == "skipped"
    assert job.last_error == "sensitive_content_filtered"
    assert summarize.await_count == 0
    assert await db_session.scalar(select(ConversationRecallSummary)) is None


@pytest.mark.asyncio
async def test_worker_retries_transient_summarizer_failure(db_session: AsyncSession) -> None:
    await _seed_job(db_session)
    summarize = AsyncMock(side_effect=RuntimeError("local model unavailable"))

    await process_one_recall_job(db_session, summarize=summarize)

    job = await db_session.get(MemoryOutboxJob, "worker-job")
    assert job.status == "pending"
    assert job.attempts == 1
    assert job.last_error == "RuntimeError"
    assert job.lease_until is None
    assert job.available_at.replace(tzinfo=UTC) > datetime.now(UTC)


@pytest.mark.asyncio
async def test_worker_rechecks_consent_after_summarization(db_session: AsyncSession) -> None:
    await _seed_job(db_session)

    async def disable_recall(_: str) -> str:
        account = await db_session.get(Account, "worker-account")
        account.past_chat_recall_enabled = False
        await db_session.flush()
        return "This should not be stored."

    await process_one_recall_job(db_session, summarize=disable_recall)

    job = await db_session.get(MemoryOutboxJob, "worker-job")
    assert job.status == "skipped"
    assert job.last_error == "consent_changed_during_processing"
    assert await db_session.scalar(select(ConversationRecallSummary)) is None


@pytest.mark.asyncio
async def test_worker_processes_durable_account_vector_cleanup(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = Account(
        id="cleanup-owner",
        username="cleanup-owner",
        display_name="Cleanup Owner",
        password_hash="!test!",
    )
    job = MemoryVectorCleanupJob(id="cleanup-job", owner_id=account.id)
    db_session.add_all([account, job])
    await db_session.flush()
    from app.services.memory_vector_index import memory_vector_index

    delete_owner = AsyncMock()
    monkeypatch.setattr(memory_vector_index, "delete_owner", delete_owner)

    processed = await process_one_vector_cleanup_job(db_session)

    saved = await db_session.get(MemoryVectorCleanupJob, job.id)
    assert processed is True
    delete_owner.assert_awaited_once_with(account.id)
    assert saved.status == "done"


@pytest.mark.asyncio
async def test_worker_reclaims_expired_vector_cleanup_lease(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = Account(
        id="cleanup-recovery-owner",
        username="cleanup-recovery-owner",
        display_name="Cleanup Recovery Owner",
        password_hash="!test!",
    )
    job = MemoryVectorCleanupJob(
        id="cleanup-recovery-job",
        owner_id=account.id,
        status="processing",
        attempts=1,
        lease_until=datetime.now(UTC) - timedelta(seconds=1),
    )
    db_session.add_all([account, job])
    await db_session.flush()
    from app.services.memory_vector_index import memory_vector_index

    delete_owner = AsyncMock()
    monkeypatch.setattr(memory_vector_index, "delete_owner", delete_owner)

    processed = await process_one_vector_cleanup_job(db_session)

    saved = await db_session.get(MemoryVectorCleanupJob, job.id)
    assert processed is True
    delete_owner.assert_awaited_once_with(account.id)
    assert saved.status == "done"
    assert saved.attempts == 2
