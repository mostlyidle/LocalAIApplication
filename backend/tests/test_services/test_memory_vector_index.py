"""Tests for account-filtered past-chat vector indexing and SQL validation."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from qdrant_client import AsyncQdrantClient

from app.config import settings
from app.models.db_models import Account, Conversation, ConversationRecallSummary, Message
from app.services.embeddings import embedding_service
from app.services.memory_vector_index import MemoryVectorIndex
from app.services.rag_store import ACCOUNT_MEMORY_COLLECTION, RagCollectionSchemaError, RagStore

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def memory_index(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "ollama_embedding_dimension", 3)
    monkeypatch.setattr(
        embedding_service,
        "get_identity",
        AsyncMock(
            return_value={
                "embedding_model": "test:latest",
                "embedding_digest": "test-digest",
                "embedding_profile": "plain-v1",
            }
        ),
    )
    monkeypatch.setattr(embedding_service, "embed_texts", AsyncMock(return_value=[[1.0, 0.0, 0.0]]))
    monkeypatch.setattr(embedding_service, "embed_text", AsyncMock(return_value=[1.0, 0.0, 0.0]))
    client = AsyncQdrantClient(":memory:")
    index = MemoryVectorIndex(client)
    yield index
    await index.close()


async def _seed_summary(db: AsyncSession) -> ConversationRecallSummary:
    account = Account(
        id="vector-account",
        username="vector-account",
        display_name="Vector Account",
        password_hash="!test!",
        memory_enabled=True,
        past_chat_recall_enabled=True,
        memory_epoch=2,
    )
    conversation = Conversation(
        id="vector-conversation", owner_id=account.id, title="Earlier discussion"
    )
    message = Message(
        id="vector-source-message",
        conversation_id=conversation.id,
        role="assistant",
        content="A response",
    )
    summary = ConversationRecallSummary(
        id="22222222-2222-4222-8222-222222222222",
        owner_id=account.id,
        conversation_id=conversation.id,
        source_message_id=message.id,
        memory_epoch=2,
        content="The user prefers concise replies.",
    )
    db.add_all([account, conversation, message, summary])
    await db.flush()
    return summary


@pytest.mark.asyncio
async def test_search_returns_only_sql_validated_owned_summary(
    db_session: AsyncSession, memory_index: MemoryVectorIndex
) -> None:
    summary = await _seed_summary(db_session)
    assert await memory_index.upsert_summary(db_session, summary) is True

    results = await memory_index.search_summaries(
        db_session,
        owner_id="vector-account",
        memory_epoch=2,
        query="How should responses be written?",
    )

    assert results == [
        {
            "type": "past_conversation",
            "conversation_id": "vector-conversation",
            "title": "Earlier discussion",
            "content": "The user prefers concise replies.",
        }
    ]
    assert (
        await memory_index.search_summaries(
            db_session,
            owner_id="another-account",
            memory_epoch=2,
            query="How should responses be written?",
        )
        == []
    )


@pytest.mark.asyncio
async def test_search_rejects_stale_revision_and_excluded_conversation(
    db_session: AsyncSession, memory_index: MemoryVectorIndex
) -> None:
    summary = await _seed_summary(db_session)
    await memory_index.upsert_summary(db_session, summary)
    summary.revision = 2
    await db_session.flush()

    stale_results = await memory_index.search_summaries(
        db_session,
        owner_id="vector-account",
        memory_epoch=2,
        query="How should responses be written?",
    )
    conversation = await db_session.get(Conversation, "vector-conversation")
    conversation.exclude_from_memory = True
    await db_session.flush()
    excluded_results = await memory_index.search_summaries(
        db_session,
        owner_id="vector-account",
        memory_epoch=2,
        query="How should responses be written?",
    )

    assert stale_results == []
    assert excluded_results == []


@pytest.mark.asyncio
async def test_delete_owner_removes_only_that_accounts_vectors(
    db_session: AsyncSession, memory_index: MemoryVectorIndex
) -> None:
    summary = await _seed_summary(db_session)
    await memory_index.upsert_summary(db_session, summary)
    await memory_index.delete_owner("vector-account")

    results = await memory_index.search_summaries(
        db_session,
        owner_id="vector-account",
        memory_epoch=2,
        query="How should responses be written?",
    )

    assert results == []


@pytest.mark.asyncio
async def test_index_write_is_removed_if_conversation_is_excluded_mid_write(
    db_session: AsyncSession,
    memory_index: MemoryVectorIndex,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = await _seed_summary(db_session)
    upsert = memory_index._client.upsert

    async def upsert_then_exclude(**kwargs):
        await upsert(**kwargs)
        conversation = await db_session.get(Conversation, "vector-conversation")
        conversation.exclude_from_memory = True
        await db_session.flush()

    monkeypatch.setattr(memory_index._client, "upsert", upsert_then_exclude)

    assert await memory_index.upsert_summary(db_session, summary) is False
    assert (
        await memory_index.search_summaries(
            db_session,
            owner_id="vector-account",
            memory_epoch=2,
            query="How should responses be written?",
        )
        == []
    )


@pytest.mark.asyncio
async def test_private_memory_collection_is_hidden_from_ordinary_rag_operations(
    db_session: AsyncSession, memory_index: MemoryVectorIndex
) -> None:
    summary = await _seed_summary(db_session)
    await memory_index.upsert_summary(db_session, summary)
    ordinary_rag = RagStore("http://unused", client=memory_index._client)

    assert await ordinary_rag.list_collections() == []
    with pytest.raises(RagCollectionSchemaError):
        await ordinary_rag.delete_collection(ACCOUNT_MEMORY_COLLECTION)
