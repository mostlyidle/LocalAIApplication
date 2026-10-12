"""Account isolation for chat history and uploaded documents."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.routes.chat import _resolve_uploaded_paths
from app.models.db_models import Account, AccountSession, Conversation, Document, Message
from app.models.enums import MessageRole
from app.services.auth import AuthenticatedSession

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


def _principal(account: Account) -> AuthenticatedSession:
    return AuthenticatedSession(
        account=account,
        session=AccountSession(
            id=str(uuid.uuid4()),
            account_id=account.id,
            token_hash="0" * 64,
            csrf_token="test-csrf-token",
            expires_at=datetime.now(UTC),
        ),
    )


def _account(account_id: str, username: str) -> Account:
    return Account(
        id=account_id,
        username=username,
        display_name=username.title(),
        password_hash="!test!",
    )


async def test_chat_routes_hide_another_accounts_history(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Conversation listing, reading, and continuing are scoped to the principal."""
    alice = _account("alice-account", "alice")
    bob = _account("bob-account", "bob")
    db_session.add_all([alice, bob])
    db_session.add_all(
        [
            Conversation(id="alice-chat", owner_id=alice.id, title="Alice private"),
            Conversation(id="bob-chat", owner_id=bob.id, title="Bob chat"),
            Message(conversation_id="alice-chat", role=MessageRole.USER, content="Alice secret"),
            Message(conversation_id="bob-chat", role=MessageRole.USER, content="Bob message"),
        ]
    )
    await db_session.commit()
    app = client._transport.app
    from app.dependencies import get_authenticated_session

    app.dependency_overrides[get_authenticated_session] = lambda: _principal(bob)

    listed = await client.get("/api/v1/chat/conversations")
    assert [row["id"] for row in listed.json()] == ["bob-chat"]
    hidden = await client.get("/api/v1/chat/conversations/alice-chat")
    assert hidden.status_code == 404
    continue_hidden = await client.post(
        "/api/v1/chat", json={"content": "follow up", "conversation_id": "alice-chat"}
    )
    assert continue_hidden.status_code == 404
    delete_hidden = await client.delete("/api/v1/chat/conversations/alice-chat")
    assert delete_hidden.status_code == 404
    assert (
        await db_session.scalar(select(Conversation.id).where(Conversation.id == "alice-chat"))
        == "alice-chat"
    )


async def test_document_routes_hide_files_owned_by_another_account(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path
) -> None:
    """Cross-account read/delete attempts cannot reveal or remove another upload."""
    alice = _account("alice-doc-account", "alice-doc")
    bob = _account("bob-doc-account", "bob-doc")
    alice_file = tmp_path / "alice-private.txt"
    alice_file.write_text("private", encoding="utf-8")
    db_session.add_all([alice, bob])
    db_session.add(
        Document(
            id="alice-document",
            owner_id=alice.id,
            filename="private.txt",
            format="text",
            size_bytes=7,
            storage_path=str(alice_file),
        )
    )
    db_session.add(
        Document(
            id="bob-document",
            owner_id=bob.id,
            filename="bob.txt",
            format="text",
            size_bytes=0,
            storage_path=str(tmp_path / "bob.txt"),
        )
    )
    await db_session.commit()
    app = client._transport.app
    from app.dependencies import get_authenticated_session

    app.dependency_overrides[get_authenticated_session] = lambda: _principal(bob)

    listed = await client.get("/api/v1/documents")
    assert [row["id"] for row in listed.json()] == ["bob-document"]
    hidden = await client.get("/api/v1/documents/alice-document")
    assert hidden.status_code == 404
    deleted = await client.delete("/api/v1/documents/alice-document")
    assert deleted.status_code == 404
    assert alice_file.read_text(encoding="utf-8") == "private"
    with pytest.raises(HTTPException) as error:
        await _resolve_uploaded_paths(["alice-document"], bob.id, db=db_session)
    assert error.value.status_code == 404
