"""Authentication route and cookie/CSRF behavior."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.main import create_app
from app.models.db_models import Account
from app.services.accounts import hash_password

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


async def test_login_refresh_and_logout(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    """Login issues an HttpOnly cookie and logout requires the current CSRF token."""
    from app.dependencies import get_authenticated_session

    client._transport.app.dependency_overrides.pop(get_authenticated_session)
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    db_session.add(
        Account(
            username="alice",
            display_name="Alice",
            password_hash=hash_password("correct horse battery staple"),
        )
    )
    await db_session.commit()

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "correct horse battery staple"},
    )
    assert login.status_code == 200
    assert login.headers["set-cookie"].startswith("localai_session=")
    assert "httponly" in login.headers["set-cookie"].lower()
    assert "samesite=strict" in login.headers["set-cookie"].lower()
    initial_csrf = login.json()["csrf_token"]

    refreshed = await client.get("/api/v1/auth/me")
    assert refreshed.status_code == 200
    assert refreshed.json()["account"]["username"] == "alice"
    csrf_token = refreshed.json()["csrf_token"]
    assert csrf_token == initial_csrf

    rejected = await client.post("/api/v1/auth/logout")
    assert rejected.status_code == 403
    wrong_token = await client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": "not-the-session-token"}
    )
    assert wrong_token.status_code == 403
    logout = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf_token})
    assert logout.status_code == 204
    assert (await client.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.parametrize(
    ("username", "password"),
    [("missing", "correct horse battery staple"), ("legacy-import-disabled", "!disabled!")],
)
async def test_login_rejects_unknown_and_legacy_accounts(
    client: AsyncClient, username: str, password: str
) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password."


async def test_chat_and_document_routes_require_a_session(client: AsyncClient) -> None:
    from app.dependencies import get_authenticated_session

    client._transport.app.dependency_overrides.pop(get_authenticated_session)
    assert (await client.get("/api/v1/chat/conversations")).status_code == 401
    assert (await client.get("/api/v1/documents")).status_code == 401
    assert (
        await client.post(
            "/api/v1/meetings",
            json={
                "consent_policy_version": "meeting-consent-v1",
                "consent_attested_at": "2026-10-12T12:00:00Z",
            },
        )
    ).status_code == 401


async def test_agent_and_resource_routes_require_a_session(client: AsyncClient) -> None:
    from app.dependencies import get_authenticated_session

    client._transport.app.dependency_overrides.pop(get_authenticated_session)
    requests = [
        client.get("/api/v1/agents"),
        client.get("/api/v1/tools"),
        client.post("/api/v1/tasks", json={"prompt": "hello"}),
        client.get("/api/v1/sql/connections"),
        client.get("/api/v1/sql/schema"),
        client.get("/api/v1/rag/collections"),
        client.post("/api/v1/rag/search", json={"query": "hello"}),
        client.post("/api/v1/rag/ingest", json={"document_id": "private-doc"}),
    ]
    responses = await asyncio.gather(*requests)
    assert [response.status_code for response in responses] == [401] * len(requests)


def test_chat_websocket_rejects_untrusted_origin() -> None:
    """The browser stream checks origin before looking up a session."""
    client = TestClient(create_app())
    with (
        pytest.raises(WebSocketDisconnect) as disconnected,
        client.websocket_connect(
            "/api/v1/chat/stream", headers={"origin": "https://attacker.example"}
        ),
    ):
        pass
    assert disconnected.value.code == 4403
