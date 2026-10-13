"""Tests for private GitHub App authorization and encrypted token handling."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.models.db_models import (
    LEGACY_ACCOUNT_ID,
    Account,
    AccountSession,
    GitHubConnection,
    GitHubOAuthState,
    GitHubRepositorySelection,
)
from app.services.github_oauth import GitHubTokenSet, decrypt_token


def _configure_github(monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "github_app_client_id", "test-client-id")
    monkeypatch.setattr(settings, "github_app_client_secret", "test-client-secret")
    monkeypatch.setattr(
        settings, "github_app_callback_url", "http://localhost:8000/api/v1/github/callback"
    )
    monkeypatch.setattr(settings, "github_app_slug", "local-ai-test")
    monkeypatch.setattr(settings, "github_frontend_url", "http://localhost:3000")
    monkeypatch.setattr(
        settings, "github_token_encryption_key", Fernet.generate_key().decode("ascii")
    )


async def _ensure_session(db_session, authenticated_test_session) -> None:
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    authenticated_test_session.session.expires_at = expires_at
    db_session.add(
        Account(
            id=LEGACY_ACCOUNT_ID,
            username="github-owner",
            display_name="GitHub Owner",
            password_hash="!test!",
        )
    )
    db_session.add(
        AccountSession(
            id=authenticated_test_session.session.id,
            account_id=LEGACY_ACCOUNT_ID,
            token_hash="1" * 64,
            csrf_token=authenticated_test_session.session.csrf_token,
            expires_at=expires_at,
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_github_connection_requires_server_configuration(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "github_app_client_id", None)
    response = await client.post(
        "/api/v1/github/connect", headers={"X-CSRF-Token": "test-csrf-token"}
    )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_oauth_state_is_one_time_and_tokens_are_encrypted(
    client, db_session, authenticated_test_session, monkeypatch
):
    _configure_github(monkeypatch)
    await _ensure_session(db_session, authenticated_test_session)
    exchange = AsyncMock(
        return_value=(
            GitHubTokenSet(
                access_token="ghu-secret-access",
                refresh_token="ghr-secret-refresh",
                expires_at=datetime.now(UTC) + timedelta(hours=8),
                refresh_expires_at=datetime.now(UTC) + timedelta(days=180),
            ),
            "12345",
            "octocat",
        )
    )
    monkeypatch.setattr("app.api.routes.github.github_oauth_client.exchange_code", exchange)

    start = await client.post("/api/v1/github/connect", headers={"X-CSRF-Token": "test-csrf-token"})
    assert start.status_code == 200
    authorization_url = start.json()["authorization_url"]
    params = parse_qs(urlparse(authorization_url).query)
    assert params["scope"] == ["offline_access"]
    state = params["state"][0]
    assert re.fullmatch(r"[A-Za-z0-9_-]{40,}", state)
    assert (
        await db_session.get(
            GitHubOAuthState,
            hashlib.sha256(state.encode()).hexdigest(),
        )
        is not None
    )

    callback = await client.get(
        "/api/v1/github/callback", params={"state": state, "code": "single-use-code"}
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "http://localhost:3000/settings?github=connected"
    exchange.assert_awaited_once_with("single-use-code")

    connection = await db_session.scalar(select(GitHubConnection))
    assert connection is not None
    assert connection.github_login == "octocat"
    assert connection.encrypted_access_token != "ghu-secret-access"
    assert decrypt_token(connection.encrypted_access_token) == "ghu-secret-access"
    assert decrypt_token(connection.encrypted_refresh_token) == "ghr-secret-refresh"

    replay = await client.get(
        "/api/v1/github/callback", params={"state": state, "code": "replayed-code"}
    )
    assert replay.status_code == 400
    assert (await client.get("/api/v1/github/connection")).json()["login"] == "octocat"


@pytest.mark.asyncio
async def test_disconnect_revokes_remote_grant_before_deleting_local_tokens(
    client, db_session, authenticated_test_session, monkeypatch
):
    _configure_github(monkeypatch)
    await _ensure_session(db_session, authenticated_test_session)
    from app.services.github_oauth import encrypt_token

    db_session.add(
        GitHubConnection(
            owner_id=LEGACY_ACCOUNT_ID,
            github_user_id="12345",
            github_login="octocat",
            encrypted_access_token=encrypt_token("ghu-disconnect-me"),
            encrypted_refresh_token=encrypt_token("ghr-refresh-me"),
            expires_at=datetime.now(UTC) + timedelta(hours=8),
            refresh_expires_at=datetime.now(UTC) + timedelta(days=180),
        )
    )
    await db_session.commit()
    revoke = AsyncMock()
    monkeypatch.setattr("app.api.routes.github.github_oauth_client.revoke", revoke)

    response = await client.delete(
        "/api/v1/github/connection", headers={"X-CSRF-Token": "test-csrf-token"}
    )
    assert response.status_code == 204
    revoke.assert_awaited_once_with("ghu-disconnect-me")
    assert await db_session.scalar(select(GitHubConnection)) is None


@pytest.mark.asyncio
async def test_expired_access_token_is_rotated_and_stored_encrypted(db_session, monkeypatch):
    _configure_github(monkeypatch)
    from app.services.github_oauth import encrypt_token, github_oauth_client

    now = datetime.now(UTC)
    connection = GitHubConnection(
        owner_id=LEGACY_ACCOUNT_ID,
        github_user_id="12345",
        github_login="octocat",
        encrypted_access_token=encrypt_token("ghu-expired"),
        encrypted_refresh_token=encrypt_token("ghr-current"),
        expires_at=now - timedelta(minutes=1),
        refresh_expires_at=now + timedelta(days=30),
    )
    db_session.add(
        Account(
            id=LEGACY_ACCOUNT_ID,
            username="github-refresh-owner",
            display_name="GitHub Owner",
            password_hash="!test!",
        )
    )
    db_session.add(connection)
    await db_session.commit()
    rotate = AsyncMock(
        return_value=GitHubTokenSet(
            access_token="ghu-refreshed",
            refresh_token="ghr-rotated",
            expires_at=now + timedelta(hours=8),
            refresh_expires_at=now + timedelta(days=180),
        )
    )
    monkeypatch.setattr(github_oauth_client, "refresh", rotate)

    token = await github_oauth_client.access_token(connection, db_session)

    assert token == "ghu-refreshed"
    rotate.assert_awaited_once_with("ghr-current")
    assert decrypt_token(connection.encrypted_access_token) == "ghu-refreshed"
    assert decrypt_token(connection.encrypted_refresh_token) == "ghr-rotated"
    assert connection.encrypted_access_token != "ghu-refreshed"


@pytest.mark.asyncio
async def test_github_oauth_http_exchange_profile_and_revoke_use_expected_tokens(monkeypatch):
    _configure_github(monkeypatch)
    from app.config import settings
    from app.services.github_oauth import github_oauth_client

    monkeypatch.setattr(settings, "github_api_url", "https://github.test")
    monkeypatch.setattr(settings, "github_oauth_url", "https://github.test/login/oauth")
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/login/oauth/access_token":
            assert parse_qs(request.content.decode())["code"] == ["single-use"]
            return httpx.Response(
                200,
                json={
                    "access_token": "ghu-test-access",
                    "refresh_token": "ghr-test-refresh",
                    "expires_in": 28_800,
                    "refresh_token_expires_in": 15_897_600,
                },
            )
        if request.url.path == "/user":
            assert request.headers["authorization"] == "Bearer ghu-test-access"
            return httpx.Response(200, json={"id": 123, "login": "octocat"})
        if request.url.path == "/applications/test-client-id/grant":
            assert request.headers["authorization"].startswith("Basic ")
            assert request.read() == b'{"access_token":"ghu-test-access"}'
            return httpx.Response(204)
        return httpx.Response(404)

    real_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(
        "app.services.github_oauth.httpx.AsyncClient",
        lambda **kwargs: real_async_client(transport=transport, **kwargs),
    )

    token_set, user_id, login = await github_oauth_client.exchange_code("single-use")
    assert (user_id, login) == ("123", "octocat")
    assert token_set.access_token == "ghu-test-access"
    await github_oauth_client.revoke(token_set.access_token)
    assert [request.url.path for request in seen] == [
        "/login/oauth/access_token",
        "/user",
        "/applications/test-client-id/grant",
    ]


@pytest.mark.asyncio
async def test_repository_list_is_account_scoped_and_selection_is_explicit(
    client, db_session, authenticated_test_session, monkeypatch
):
    _configure_github(monkeypatch)
    await _ensure_session(db_session, authenticated_test_session)
    from app.services.github_oauth import github_oauth_client

    db_session.add(
        GitHubConnection(
            owner_id=LEGACY_ACCOUNT_ID,
            github_user_id="12345",
            github_login="octocat",
            encrypted_access_token="unused",
            encrypted_refresh_token="unused",
            expires_at=datetime.now(UTC) + timedelta(hours=8),
            refresh_expires_at=datetime.now(UTC) + timedelta(days=180),
        )
    )
    db_session.add(
        Account(
            id="00000000-0000-4000-8000-000000000001",
            username="other-github-owner",
            display_name="Other Owner",
            password_hash="!test!",
        )
    )
    db_session.add(
        GitHubRepositorySelection(
            owner_id="00000000-0000-4000-8000-000000000001",
            repository_id="42",
            full_name="other/private",
            html_url="https://github.com/other/private",
            default_branch="main",
            is_private=True,
        )
    )
    await db_session.commit()
    monkeypatch.setattr(github_oauth_client, "access_token", AsyncMock(return_value="ghu-test"))
    monkeypatch.setattr(
        github_oauth_client,
        "api_get_json",
        AsyncMock(
            return_value=[
                {
                    "id": 42,
                    "full_name": "octocat/hello-world",
                    "html_url": "https://github.com/octocat/hello-world",
                    "default_branch": "main",
                    "private": False,
                }
            ]
        ),
    )

    listed = await client.get("/api/v1/github/repositories")
    assert listed.status_code == 200
    repo = listed.json()["repositories"][0]
    assert repo == {
        "repository_id": "42",
        "full_name": "octocat/hello-world",
        "html_url": "https://github.com/octocat/hello-world",
        "default_branch": "main",
        "is_private": False,
        "selected": False,
    }
    github_oauth_client.api_get_json.assert_awaited_once_with(
        "/user/repos",
        "ghu-test",
        {
            "affiliation": "owner,collaborator,organization_member",
            "sort": "full_name",
            "per_page": 100,
            "page": 1,
        },
    )

    selected = await client.put(
        "/api/v1/github/repositories/42/selection",
        json={"selected": True},
        headers={"X-CSRF-Token": "test-csrf-token"},
    )
    assert selected.status_code == 204
    saved = await db_session.scalar(
        select(GitHubRepositorySelection).where(
            GitHubRepositorySelection.owner_id == LEGACY_ACCOUNT_ID
        )
    )
    assert saved is not None and saved.full_name == "octocat/hello-world"

    listed_again = await client.get("/api/v1/github/repositories")
    assert listed_again.json()["repositories"][0]["selected"] is True

    monkeypatch.setattr(github_oauth_client, "api_get_json", AsyncMock(return_value=[]))
    unavailable = await client.put(
        "/api/v1/github/repositories/999/selection",
        json={"selected": True},
        headers={"X-CSRF-Token": "test-csrf-token"},
    )
    assert unavailable.status_code == 404


@pytest.mark.asyncio
async def test_repository_enumeration_follows_pagination(monkeypatch):
    from app.api.routes.github import _accessible_repositories
    from app.services.github_oauth import github_oauth_client

    first_page = [
        {
            "id": repository_id,
            "full_name": f"octocat/project-{repository_id}",
            "html_url": f"https://github.com/octocat/project-{repository_id}",
            "default_branch": "main",
            "private": False,
        }
        for repository_id in range(100)
    ]
    last_page = [{
        "id": 100,
        "full_name": "octocat/project-100",
        "html_url": "https://github.com/octocat/project-100",
        "default_branch": "main",
        "private": True,
    }]
    fetch_page = AsyncMock(side_effect=[first_page, last_page])
    monkeypatch.setattr(github_oauth_client, "api_get_json", fetch_page)

    repositories = await _accessible_repositories("ghu-test")

    assert len(repositories) == 101
    assert fetch_page.await_count == 2
    assert fetch_page.await_args_list[0].args[2]["page"] == 1
    assert fetch_page.await_args_list[1].args[2]["page"] == 2
