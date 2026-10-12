"""Authentication route and cookie/CSRF behavior."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.config import settings
from app.models.db_models import Account
from app.services.accounts import hash_password

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


async def test_login_refresh_and_logout(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    """Login issues an HttpOnly cookie and logout requires the current CSRF token."""
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
    assert csrf_token != initial_csrf

    rejected = await client.post("/api/v1/auth/logout")
    assert rejected.status_code == 403
    stale_token = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": initial_csrf})
    assert stale_token.status_code == 403
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
