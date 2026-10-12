"""Tests for account-owned explicit memory records and controls."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import (
    LEGACY_ACCOUNT_ID,
    Account,
    Conversation,
    ConversationRecallSummary,
    MemoryOutboxJob,
    Message,
)


async def _ensure_account(db: AsyncSession) -> Account:
    account = await db.get(Account, LEGACY_ACCOUNT_ID)
    if account is None:
        account = Account(
            id=LEGACY_ACCOUNT_ID,
            username="memory-test-account",
            display_name="Memory Test",
            password_hash="!test!",
            memory_epoch=0,
        )
        db.add(account)
        await db.commit()
    return account


@pytest.mark.asyncio
async def test_create_list_and_search_memories(client: AsyncClient, db_session: AsyncSession):
    response = await client.post(
        "/api/v1/memory",
        json={"kind": "preference", "content": "  Use concise answers  ", "project_scope": "Work"},
        headers={"X-CSRF-Token": "test-csrf-token"},
    )

    assert response.status_code == 201
    created = response.json()
    assert created["content"] == "Use concise answers"
    assert created["project_scope"] == "Work"
    assert created["revision"] == 1

    listed = await client.get("/api/v1/memory?q=concise")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["memories"][0]["id"] == created["id"]
    assert (await client.get("/api/v1/memory?q=missing")).json()["total"] == 0


@pytest.mark.asyncio
async def test_memory_source_must_belong_to_signed_in_account(
    client: AsyncClient, db_session: AsyncSession
):
    db_session.add_all(
        [
            Account(
                id="other-account",
                username="other-memory-account",
                display_name="Other Account",
                password_hash="!test!",
            ),
            Conversation(id="owned-memory-source", owner_id=LEGACY_ACCOUNT_ID),
            Conversation(id="foreign-memory-source", owner_id="other-account"),
        ]
    )
    db_session.add_all(
        [
            Message(
                id="owned-memory-message",
                conversation_id="owned-memory-source",
                role="user",
                content="A preference",
            ),
            Message(
                id="foreign-memory-message",
                conversation_id="foreign-memory-source",
                role="user",
                content="Private",
            ),
        ]
    )
    await db_session.commit()

    allowed = await client.post(
        "/api/v1/memory",
        json={"content": "Keep reports short", "source_message_id": "owned-memory-message"},
        headers={"X-CSRF-Token": "test-csrf-token"},
    )
    denied = await client.post(
        "/api/v1/memory",
        json={"content": "Keep reports short", "source_message_id": "foreign-memory-message"},
        headers={"X-CSRF-Token": "test-csrf-token"},
    )
    assert allowed.status_code == 201
    assert allowed.json()["source_conversation_id"] == "owned-memory-source"
    assert denied.status_code == 404


@pytest.mark.asyncio
async def test_memory_links_live_chat_turn_to_persisted_owned_message(
    client: AsyncClient, db_session: AsyncSession
):
    turn_id = "8a948d4f-8194-4e85-aa5f-00fc13bd6cb5"
    db_session.add_all(
        [
            Conversation(id="owned-live-turn", owner_id=LEGACY_ACCOUNT_ID),
            Message(
                id="persisted-live-user-message",
                conversation_id="owned-live-turn",
                role="user",
                content="My preferred color is cobalt blue.",
                client_turn_id=turn_id,
                turn_status="completed",
            ),
        ]
    )
    await db_session.commit()

    response = await client.post(
        "/api/v1/memory",
        json={
            "kind": "preference",
            "content": "Cobalt blue is my preferred color.",
            "source_conversation_id": "owned-live-turn",
            "source_client_turn_id": turn_id,
        },
        headers={"X-CSRF-Token": "test-csrf-token"},
    )

    assert response.status_code == 201
    assert response.json()["source_message_id"] == "persisted-live-user-message"


@pytest.mark.asyncio
async def test_memory_client_turn_source_is_owner_scoped(
    client: AsyncClient, db_session: AsyncSession
):
    db_session.add_all(
        [
            Account(
                id="foreign-turn-owner",
                username="foreign-turn-owner",
                display_name="Foreign Owner",
                password_hash="!test!",
            ),
            Conversation(id="foreign-turn-conversation", owner_id="foreign-turn-owner"),
            Message(
                id="foreign-turn-message",
                conversation_id="foreign-turn-conversation",
                role="user",
                content="Private text",
                client_turn_id="foreign-turn-id",
            ),
        ]
    )
    await db_session.commit()

    response = await client.post(
        "/api/v1/memory",
        json={"content": "Try foreign memory", "source_client_turn_id": "foreign-turn-id"},
        headers={"X-CSRF-Token": "test-csrf-token"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_conversation_can_opt_out_of_memory_and_only_by_its_owner(
    client: AsyncClient, db_session: AsyncSession
):
    db_session.add_all(
        [
            Account(
                id="recall-foreign-owner",
                username="recall-foreign-owner",
                display_name="Recall Foreign Owner",
                password_hash="!test!",
            ),
            Conversation(id="recall-owned-conversation", owner_id=LEGACY_ACCOUNT_ID),
            Conversation(id="recall-foreign-conversation", owner_id="recall-foreign-owner"),
        ]
    )
    await db_session.commit()

    allowed = await client.patch(
        "/api/v1/memory/conversations/recall-owned-conversation/settings",
        json={"exclude_from_memory": True},
        headers={"X-CSRF-Token": "test-csrf-token"},
    )
    forbidden = await client.patch(
        "/api/v1/memory/conversations/recall-foreign-conversation/settings",
        json={"exclude_from_memory": True},
        headers={"X-CSRF-Token": "test-csrf-token"},
    )
    detail = await client.get("/api/v1/chat/conversations/recall-owned-conversation")

    assert allowed.status_code == 200
    assert allowed.json() == {"exclude_from_memory": True}
    assert forbidden.status_code == 404
    assert detail.json()["exclude_from_memory"] is True


@pytest.mark.asyncio
async def test_update_requires_matching_revision_and_delete_hides_memory(
    client: AsyncClient,
):
    created = await client.post(
        "/api/v1/memory",
        json={"content": "Use blue", "kind": "preference"},
        headers={"X-CSRF-Token": "test-csrf-token"},
    )
    memory_id = created.json()["id"]
    updated = await client.patch(
        f"/api/v1/memory/{memory_id}",
        json={"revision": 1, "content": "Use cobalt blue"},
        headers={"X-CSRF-Token": "test-csrf-token"},
    )
    stale = await client.patch(
        f"/api/v1/memory/{memory_id}",
        json={"revision": 1, "content": "Use green"},
        headers={"X-CSRF-Token": "test-csrf-token"},
    )
    deleted = await client.delete(
        f"/api/v1/memory/{memory_id}?revision=2",
        headers={"X-CSRF-Token": "test-csrf-token"},
    )
    listed = await client.get("/api/v1/memory")

    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert updated.json()["content"] == "Use cobalt blue"
    assert stale.status_code == 409
    assert deleted.status_code == 204
    assert listed.json()["total"] == 0


@pytest.mark.asyncio
async def test_settings_are_independent_and_delete_all_advances_epoch(
    client: AsyncClient, db_session: AsyncSession
):
    account = await _ensure_account(db_session)
    created = await client.post(
        "/api/v1/memory",
        json={"content": "A saved preference"},
        headers={"X-CSRF-Token": "test-csrf-token"},
    )
    enabled = await client.patch(
        "/api/v1/memory/settings",
        json={"memory_enabled": True},
        headers={"X-CSRF-Token": "test-csrf-token"},
    )
    assert enabled.json() == {"memory_enabled": True, "past_chat_recall_enabled": False}
    await client.patch(
        "/api/v1/memory/settings",
        json={"past_chat_recall_enabled": True},
        headers={"X-CSRF-Token": "test-csrf-token"},
    )
    conversation = Conversation(id="delete-all-recall-chat", owner_id=account.id)
    source = Message(
        id="delete-all-recall-source",
        conversation_id=conversation.id,
        role="assistant",
        content="A past reply",
    )
    db_session.add_all(
        [
            conversation,
            source,
            MemoryOutboxJob(
                id="delete-all-recall-job",
                owner_id=account.id,
                conversation_id=conversation.id,
                source_message_id=source.id,
                memory_epoch=account.memory_epoch,
                available_at=account.created_at,
            ),
            ConversationRecallSummary(
                id="delete-all-recall-summary",
                owner_id=account.id,
                conversation_id=conversation.id,
                source_message_id=source.id,
                memory_epoch=account.memory_epoch,
                content="A derived summary",
            ),
        ]
    )
    await db_session.commit()

    cleared = await client.delete("/api/v1/memory", headers={"X-CSRF-Token": "test-csrf-token"})
    current = await db_session.scalar(select(Account).where(Account.id == account.id))
    await db_session.refresh(current)
    assert created.status_code == 201
    assert cleared.json() == {
        "deleted_count": 1,
        "memory_epoch": 1,
        "past_chat_recall_enabled": False,
    }
    assert current.memory_epoch == 1
    assert (await client.get("/api/v1/memory")).json()["total"] == 0
    assert await db_session.scalar(select(MemoryOutboxJob.id)) is None
    assert await db_session.scalar(select(ConversationRecallSummary.id)) is None
