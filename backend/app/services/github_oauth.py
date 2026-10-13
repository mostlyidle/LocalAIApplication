"""GitHub App OAuth exchange, refresh, revocation, and token encryption."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx
import structlog
from cryptography.fernet import Fernet, InvalidToken

from app.api.middleware.error_handler import AppError
from app.config import settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.db_models import GitHubConnection

logger = structlog.get_logger(__name__)
API_VERSION = "2026-03-10"


class GitHubIntegrationError(AppError):
    """A safe, user-facing error from GitHub authorization or API calls."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message, code="GITHUB_INTEGRATION_ERROR", status_code=status_code)


@dataclass(frozen=True)
class GitHubTokenSet:
    access_token: str
    refresh_token: str
    expires_at: datetime
    refresh_expires_at: datetime


def is_github_configured() -> bool:
    """Return whether the required GitHub App and encryption settings are present."""
    return all(
        (
            settings.github_app_client_id,
            settings.github_app_client_secret,
            settings.github_app_callback_url,
            settings.github_token_encryption_key,
        )
    )


def _fernet() -> Fernet:
    key = settings.github_token_encryption_key
    if not key:
        raise GitHubIntegrationError("GitHub connection is not configured on this server.", 503)
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise GitHubIntegrationError("GitHub token encryption is misconfigured.", 503) from exc


def encrypt_token(token: str) -> str:
    """Encrypt an OAuth token before storing it in the application database."""
    return _fernet().encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_token(value: str) -> str:
    """Decrypt one stored OAuth token without exposing cryptography details."""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeEncodeError) as exc:
        logger.error("github_token_decryption_failed")
        raise GitHubIntegrationError("Stored GitHub credentials could not be decrypted.", 503) from exc


def _expiry(payload: dict[str, object], field: str, now: datetime) -> datetime:
    seconds = payload.get(field)
    if not isinstance(seconds, int) or seconds <= 0:
        raise GitHubIntegrationError("GitHub did not return expiring user credentials.")
    return now + timedelta(seconds=seconds)


class GitHubOAuthClient:
    """Small HTTP client for the GitHub App user authorization flow."""

    def __init__(self) -> None:
        self._refresh_locks: dict[str, asyncio.Lock] = {}

    def authorization_url(self, state: str) -> str:
        parsed = urlparse(settings.github_app_callback_url or "")
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}:
            raise GitHubIntegrationError("GitHub callback URL must use HTTPS.", 503)
        if not settings.github_app_client_id or not settings.github_app_callback_url:
            raise GitHubIntegrationError("GitHub connection is not configured on this server.", 503)
        from urllib.parse import urlencode

        return (
            "https://github.com/login/oauth/authorize?"
            + urlencode(
                {
                    "client_id": settings.github_app_client_id,
                    "redirect_uri": settings.github_app_callback_url,
                    "state": state,
                    "scope": "offline_access",
                }
            )
        )

    async def exchange_code(self, code: str) -> tuple[GitHubTokenSet, str, str]:
        """Exchange a one-time code, then retrieve the authorized GitHub identity."""
        payload = await self._post_token(
            {"code": code, "redirect_uri": settings.github_app_callback_url}
        )
        tokens = self._tokens(payload)
        user = await self._api_get("/user", tokens.access_token)
        user_id = user.get("id")
        login = user.get("login")
        if not isinstance(user_id, int) or not isinstance(login, str) or not login:
            raise GitHubIntegrationError("GitHub did not return a valid account identity.")
        return tokens, str(user_id), login

    async def refresh(self, refresh_token: str) -> GitHubTokenSet:
        """Rotate an expired user token and its one-time refresh token."""
        payload = await self._post_token(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )
        return self._tokens(payload)

    async def access_token(self, connection: GitHubConnection, db: AsyncSession) -> str:
        """Return a usable user token, rotating encrypted credentials before expiry."""
        lock = self._refresh_locks.setdefault(connection.owner_id, asyncio.Lock())
        async with lock:
            await db.refresh(connection)
            now = datetime.now(UTC)
            expires_at = connection.expires_at.replace(tzinfo=UTC)
            if expires_at > now + timedelta(minutes=2):
                return decrypt_token(connection.encrypted_access_token)
            if connection.refresh_expires_at.replace(tzinfo=UTC) <= now:
                raise GitHubIntegrationError(
                    "The GitHub authorization expired; disconnect and reconnect the account.", 401
                )
            tokens = await self.refresh(decrypt_token(connection.encrypted_refresh_token))
            connection.encrypted_access_token = encrypt_token(tokens.access_token)
            connection.encrypted_refresh_token = encrypt_token(tokens.refresh_token)
            connection.expires_at = tokens.expires_at.replace(tzinfo=None)
            connection.refresh_expires_at = tokens.refresh_expires_at.replace(tzinfo=None)
            await db.commit()
            return tokens.access_token

    async def revoke(self, access_token: str) -> None:
        """Revoke this GitHub App authorization before deleting local credentials."""
        client_id = settings.github_app_client_id
        client_secret = settings.github_app_client_secret
        if not client_id or not client_secret:
            raise GitHubIntegrationError("GitHub connection is not configured on this server.", 503)
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.request(
                    "DELETE",
                    f"{settings.github_api_url.rstrip('/')}/applications/{client_id}/grant",
                    auth=(client_id, client_secret),
                    headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": API_VERSION},
                    json={"access_token": access_token},
                )
                if response.status_code not in {204, 404}:
                    raise GitHubIntegrationError("GitHub could not revoke the app authorization.")
        except httpx.HTTPError as exc:
            logger.warning("github_revoke_failed", error=type(exc).__name__)
            raise GitHubIntegrationError("Could not reach GitHub to revoke this connection.") from exc

    async def _post_token(self, fields: dict[str, str | None]) -> dict[str, object]:
        client_id = settings.github_app_client_id
        client_secret = settings.github_app_client_secret
        if not client_id or not client_secret:
            raise GitHubIntegrationError("GitHub connection is not configured on this server.", 503)
        form = {key: value for key, value in fields.items() if value is not None}
        form.update(client_id=client_id, client_secret=client_secret)
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"{settings.github_oauth_url.rstrip('/')}/access_token",
                    data=form,
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("github_token_exchange_failed", error=type(exc).__name__)
            raise GitHubIntegrationError("GitHub authorization could not be completed.") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
            raise GitHubIntegrationError("GitHub did not return a valid access token.")
        return payload

    async def _api_get(self, path: str, token: str) -> dict[str, object]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    f"{settings.github_api_url.rstrip('/')}{path}",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {token}",
                        "X-GitHub-Api-Version": API_VERSION,
                        "User-Agent": "LocalAIApplication",
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("github_profile_fetch_failed", error=type(exc).__name__)
            raise GitHubIntegrationError("Could not verify the GitHub account.") from exc
        if not isinstance(payload, dict):
            raise GitHubIntegrationError("GitHub returned an invalid account profile.")
        return payload

    @staticmethod
    def _tokens(payload: dict[str, object]) -> GitHubTokenSet:
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        if not isinstance(access_token, str) or not isinstance(refresh_token, str):
            raise GitHubIntegrationError(
                "GitHub must return expiring access and refresh tokens; enable token expiration."
            )
        now = datetime.now(UTC)
        return GitHubTokenSet(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=_expiry(payload, "expires_in", now),
            refresh_expires_at=_expiry(payload, "refresh_token_expires_in", now),
        )


github_oauth_client = GitHubOAuthClient()
