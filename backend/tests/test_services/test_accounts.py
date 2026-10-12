"""Account credential validation checks."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.account_admin import _create_account, _reset_password
from app.models.db_models import Account, AccountSession
from app.services.accounts import hash_password, normalize_username, verify_password


def test_password_hash_is_argon2_and_verification_is_safe() -> None:
    """Passwords are stored as one-way hashes and bad hashes never authenticate."""
    encoded = hash_password("correct horse battery staple")

    assert encoded.startswith("$argon2id$")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("incorrect password", encoded)
    assert not verify_password("anything", "!disabled!")


@pytest.mark.parametrize("username", ["legacy-import-disabled", "xy", "has spaces", "a" * 65])
def test_reserved_or_malformed_usernames_are_rejected(username: str) -> None:
    """Account names cannot collide with the quarantine identity or bypass validation."""
    with pytest.raises(ValueError):
        normalize_username(username)


def test_username_is_trimmed_and_casefolded() -> None:
    assert normalize_username("  Alice.Dev  ") == "alice.dev"


def test_password_minimum_length_is_enforced() -> None:
    with pytest.raises(ValueError, match="12 characters"):
        hash_password("too short")


async def test_operator_password_reset_revokes_sessions(async_engine, monkeypatch) -> None:
    """The operator reset path changes the credential and invalidates old sessions."""
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.account_admin.get_app_session_factory", lambda: factory)

    await _create_account("alice", "Alice", "initial secure password")
    async with factory() as session:
        account = await session.scalar(select(Account).where(Account.username == "alice"))
        assert account is not None
        session.add(
            AccountSession(
                account_id=account.id, token_hash="a" * 64, expires_at=account.created_at
            )
        )
        await session.commit()

    await _reset_password("alice", "replacement secure password")
    async with factory() as session:
        account = await session.scalar(select(Account).where(Account.username == "alice"))
        account_session = await session.scalar(select(AccountSession))

    assert account is not None
    assert account_session is not None and account_session.revoked_at is not None
    assert verify_password("replacement secure password", account.password_hash)
