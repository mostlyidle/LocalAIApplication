"""Long-lived streams close after their browser session is revoked."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.routes import chat, meetings
from app.dependencies import get_websocket_session
from app.main import create_app
from app.models.db_models import Account, AccountSession
from app.services.auth import AuthenticatedSession


def test_chat_stream_closes_when_session_is_revoked(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app()
    app.dependency_overrides[get_websocket_session] = lambda: AuthenticatedSession(
        account=Account(
            id="account-id",
            username="test",
            display_name="Test",
            password_hash="!test!",
        ),
        session=AccountSession(
            id="session-id",
            account_id="account-id",
            token_hash="a" * 64,
            csrf_token="csrf-token",
            expires_at=datetime.now(UTC),
        ),
    )
    monkeypatch.setattr(chat, "WEBSOCKET_SESSION_RECHECK_SECONDS", 0)
    monkeypatch.setattr(chat, "websocket_session_is_active", AsyncMock(return_value=False))

    with (
        TestClient(app).websocket_connect(
            "/api/v1/chat/stream", headers={"origin": "http://test"}
        ) as websocket,
        pytest.raises(WebSocketDisconnect) as disconnected,
    ):
        websocket.receive_text()

    assert disconnected.value.code == 4401


async def test_meeting_stream_stops_when_session_is_revoked(
    client, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = await client.post(
        "/api/v1/meetings",
        json={
            "consent_policy_version": "meeting-consent-v1",
            "consent_attested_at": datetime.now(UTC).isoformat(),
        },
    )
    meeting_id = created.json()["id"]
    monkeypatch.setattr(meetings, "WEBSOCKET_SESSION_RECHECK_SECONDS", 0)
    monkeypatch.setattr(meetings, "websocket_session_is_active", AsyncMock(return_value=False))

    with TestClient(app).websocket_connect(
        f"/api/v1/meetings/{meeting_id}/stream", headers={"origin": "http://localhost:3000"}
    ) as websocket:
        assert websocket.receive_json()["type"] == "status"
        with pytest.raises(WebSocketDisconnect) as disconnected:
            websocket.receive_text()

    assert disconnected.value.code == 4401
    meeting = await client.get(f"/api/v1/meetings/{meeting_id}")
    assert meeting.json()["status"] == "stopped"
