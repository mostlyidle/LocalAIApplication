"""Meeting routes never expose or mutate another account's meeting."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from app.dependencies import get_authenticated_session, get_websocket_session
from app.models.db_models import Account, AccountSession
from app.services.auth import AuthenticatedSession

if TYPE_CHECKING:
    from httpx import AsyncClient


def _consent() -> dict[str, str]:
    return {
        "consent_policy_version": "meeting-consent-v1",
        "consent_attested_at": datetime.now(UTC).isoformat(),
    }


async def test_meeting_routes_hide_foreign_meetings(
    client: AsyncClient, app, authenticated_test_session: AuthenticatedSession
) -> None:
    created = await client.post("/api/v1/meetings", json=_consent())
    assert created.status_code == 200
    meeting_id = created.json()["id"]

    other_account = AuthenticatedSession(
        account=Account(
            id="different-account",
            username="different",
            display_name="Different",
            password_hash="!test!",
        ),
        session=AccountSession(
            id="different-session",
            account_id="different-account",
            token_hash="2" * 64,
            csrf_token="other-csrf-token",
            expires_at=datetime.now(UTC),
        ),
    )
    app.dependency_overrides[get_authenticated_session] = lambda: other_account
    app.dependency_overrides[get_websocket_session] = lambda: other_account

    assert (await client.get(f"/api/v1/meetings/{meeting_id}")).status_code == 404
    assert (await client.post(f"/api/v1/meetings/{meeting_id}/stop")).status_code == 404
    assert (await client.delete(f"/api/v1/meetings/{meeting_id}")).status_code == 404
    with TestClient(app).websocket_connect(
        f"/api/v1/meetings/{meeting_id}/stream", headers={"origin": "http://localhost:3000"}
    ) as websocket:
        assert websocket.receive_json()["code"] == "NOT_FOUND"

    app.dependency_overrides[get_authenticated_session] = lambda: authenticated_test_session
    app.dependency_overrides.pop(get_websocket_session)
    assert (await client.get(f"/api/v1/meetings/{meeting_id}")).status_code == 200
