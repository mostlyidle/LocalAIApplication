"""Tests for private planner action items."""

from __future__ import annotations

import pytest

from app.models.db_models import LEGACY_ACCOUNT_ID, Account, ActionItem


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
