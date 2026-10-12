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
from app.models.db_models import Account, AccountSession, MeetingStreamTicket

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
    return _active_authenticated_session(session, account)


async def resolve_session_by_id(db: AsyncSession, session_id: str) -> AuthenticatedSession | None:
    """Resolve an active session by its server-side ID for an established socket."""
    result = await db.execute(
        select(AccountSession, Account)
        .join(Account, Account.id == AccountSession.account_id)
        .where(AccountSession.id == session_id)
    )
    row = result.one_or_none()
    if row is None:
        return None
    session, account = row
    return _active_authenticated_session(session, account)


def _active_authenticated_session(
    session: AccountSession, account: Account
) -> AuthenticatedSession | None:
    """Reject revoked, expired, or disabled sessions consistently."""
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if session.revoked_at is not None or expires_at <= datetime.now(UTC) or not account.is_enabled:
        return None
    return AuthenticatedSession(account=account, session=session)


async def resolve_meeting_stream_ticket(
    db: AsyncSession, token: str | None, meeting_id: str
) -> AuthenticatedSession | None:
    """Resolve a native meeting ticket while honoring its parent session lifetime."""
    if not token:
        return None
    ticket = await db.scalar(
        select(MeetingStreamTicket).where(
            MeetingStreamTicket.token_hash == _digest(token),
            MeetingStreamTicket.meeting_id == meeting_id,
        )
    )
    if ticket is None:
        return None
    expires_at = ticket.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= datetime.now(UTC):
        return None
    return await resolve_session_by_id(db, ticket.session_id)


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
