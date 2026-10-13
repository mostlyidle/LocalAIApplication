"""Tests for private planner action items."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import func, select

from app.models.action_item_schemas import ActionItemSuggestion
from app.models.db_models import (
    LEGACY_ACCOUNT_ID,
    Account,
    ActionItem,
    Conversation,
    Message,
)


@pytest.mark.asyncio
async def test_action_item_crud_and_revision_check(client, db_session):
    db_session.add(
        Account(
            id=LEGACY_ACCOUNT_ID,
            username="planner-owner",
            display_name="Planner Owner",
            password_hash="!test!",
        )
    )
    await db_session.commit()
    headers = {"X-CSRF-Token": "test-csrf-token"}

    created_response = await client.post(
        "/api/v1/action-items",
        json={"title": "  Send notes  ", "priority": "high"},
        headers=headers,
    )
    assert created_response.status_code == 201
    created = created_response.json()
    assert created["title"] == "Send notes"
    assert created["revision"] == 1
    assert (await client.get("/api/v1/action-items")).json()["total"] == 1

    updated_response = await client.patch(
        f"/api/v1/action-items/{created['id']}",
        json={"revision": 1, "status": "done"},
        headers=headers,
    )
    assert updated_response.status_code == 200
    assert updated_response.json()["status"] == "done"
    assert updated_response.json()["revision"] == 2

    stale_response = await client.patch(
        f"/api/v1/action-items/{created['id']}",
        json={"revision": 1, "title": "Stale edit"},
        headers=headers,
    )
    assert stale_response.status_code == 409

    deleted = await client.delete(f"/api/v1/action-items/{created['id']}", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/action-items")).json()["total"] == 0


@pytest.mark.asyncio
async def test_action_items_and_sources_are_account_scoped(client, db_session):
    db_session.add_all(
        [
            Account(
                id=LEGACY_ACCOUNT_ID,
                username="planner-owner-2",
                display_name="Planner Owner",
                password_hash="!test!",
            ),
            Account(
                id="foreign-owner",
                username="foreign-planner-owner",
                display_name="Foreign Owner",
                password_hash="!test!",
            ),
            ActionItem(id="foreign-task", owner_id="foreign-owner", title="Secret"),
        ]
    )
    await db_session.commit()

    listed = await client.get("/api/v1/action-items")
    assert listed.status_code == 200
    assert listed.json() == {"items": [], "total": 0}

    denied_update = await client.patch(
        "/api/v1/action-items/foreign-task",
        json={"revision": 1, "title": "Changed"},
        headers={"X-CSRF-Token": "test-csrf-token"},
    )
    assert denied_update.status_code == 404

    invalid = await client.post(
        "/api/v1/action-items",
        json={"title": "Use foreign source", "source_type": "chat", "source_id": "private"},
        headers={"X-CSRF-Token": "test-csrf-token"},
    )
    assert invalid.status_code == 404


@pytest.mark.asyncio
async def test_proposals_are_verbatim_cited_and_never_saved_automatically(
    client, db_session, monkeypatch
):
    db_session.add_all(
        [
            Account(
                id=LEGACY_ACCOUNT_ID,
                username="planner-proposal-owner",
                display_name="Planner Owner",
                password_hash="!test!",
            ),
            Conversation(id="planner-chat", owner_id=LEGACY_ACCOUNT_ID, title="Planning chat"),
            Message(
                id="planner-message",
                conversation_id="planner-chat",
                role="user",
                content="I will send the update tomorrow.",
            ),
        ]
    )
    await db_session.commit()
    model = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(
        return_value={
            "suggestions": [
                ActionItemSuggestion(
                    title="Send the update",
                    source_quote="I will send the update tomorrow.",
                ),
                ActionItemSuggestion(title="Invented task", source_quote="This quote is absent."),
            ]
        }
    )
    model.with_structured_output.return_value = structured
    monkeypatch.setattr("app.services.planner_agent.llm_service.get_chat_model", lambda **_: model)

    response = await client.post(
        "/api/v1/action-items/proposals",
        json={"source_type": "chat", "source_id": "planner-chat"},
        headers={"X-CSRF-Token": "test-csrf-token"},
    )
    assert response.status_code == 200
    assert response.json()["source_title"] == "Planning chat"
    assert len(response.json()["suggestions"]) == 1
    assert response.json()["suggestions"][0]["source_quote"] == "I will send the update tomorrow."
    assert await db_session.scalar(select(func.count(ActionItem.id))) == 0

    accepted = await client.post(
        "/api/v1/action-items",
        json={
            "title": "Send the update",
            "source_type": "chat",
            "source_id": "planner-chat",
            "source_quote": "I will send the update tomorrow.",
        },
        headers={"X-CSRF-Token": "test-csrf-token"},
    )
    assert accepted.status_code == 201
    assert accepted.json()["source_quote"] == "I will send the update tomorrow."

    forged = await client.post(
        "/api/v1/action-items",
        json={
            "title": "Forged citation",
            "source_type": "chat",
            "source_id": "planner-chat",
            "source_quote": "Not in the chat.",
        },
        headers={"X-CSRF-Token": "test-csrf-token"},
    )
    assert forged.status_code == 422


@pytest.mark.asyncio
async def test_private_source_is_rejected_before_calling_the_model(client, monkeypatch):
    get_model = MagicMock()
    monkeypatch.setattr("app.services.planner_agent.llm_service.get_chat_model", get_model)
    response = await client.post(
        "/api/v1/action-items/proposals",
        json={"source_type": "chat", "source_id": "another-account-chat"},
        headers={"X-CSRF-Token": "test-csrf-token"},
    )
    assert response.status_code == 404
    get_model.assert_not_called()
