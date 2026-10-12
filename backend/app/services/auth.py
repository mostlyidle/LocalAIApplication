"""Opaque browser-session lifecycle and CSRF token validation."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from app.config import settings
from app.models.db_models import Account, AccountSession

SESSION_COOKIE = "localai_session"


@dataclass(frozen=True)
class AuthenticatedSession:
    """Account and server-side session resolved from a valid cookie."""

    account: Account
    session: AccountSession


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_token() -> str:
    """Create a cryptographically random opaque token."""
    return secrets.token_urlsafe(32)


async def create_session(db: AsyncSession, account: Account) -> tuple[AccountSession, str, str]:
    """Persist token digests and return the one-time raw cookie and CSRF values."""
    session_token = new_token()
    csrf_token = new_token()
    session = AccountSession(
        account_id=account.id,
        token_hash=_digest(session_token),
        csrf_token=csrf_token,
        expires_at=datetime.now(UTC) + timedelta(hours=settings.auth_session_ttl_hours),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session, session_token, csrf_token


async def resolve_session(db: AsyncSession, token: str | None) -> AuthenticatedSession | None:
    """Return an enabled account for a live, non-revoked opaque token."""
    if not token:
        return None
    result = await db.execute(
        select(AccountSession, Account)
        .join(Account, Account.id == AccountSession.account_id)
        .where(AccountSession.token_hash == _digest(token))
    )
    row = result.one_or_none()
    if row is None:
        return None
    session, account = row
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if session.revoked_at is not None or expires_at <= datetime.now(UTC) or not account.is_enabled:
        return None
    return AuthenticatedSession(account=account, session=session)


def verify_csrf(session: AccountSession, csrf_token: str | None) -> bool:
    """Compare the request token in constant time."""
    if not csrf_token:
        return False
    return hmac.compare_digest(session.csrf_token, csrf_token)


def get_csrf_token(session: AccountSession) -> str:
    """Return the stable CSRF token bound to this authenticated session."""
    return session.csrf_token


async def revoke_session(db: AsyncSession, session: AccountSession) -> None:
    """Revoke a session once; repeated logout remains harmless."""
    if session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
        await db.commit()
