"""Account credential validation checks."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.account_admin import _assign_legacy_records, _create_account, _reset_password
from app.models.db_models import (
    LEGACY_ACCOUNT_ID,
    Account,
    AccountSession,
    Conversation,
    Document,
    Meeting,
    RagCollection,
)
from app.services.rag_store import CollectionCapabilities
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
                account_id=account.id,
                token_hash="a" * 64,
                csrf_token="test-csrf-token",
                expires_at=account.created_at,
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


async def test_legacy_assignment_defaults_to_dry_run_and_applies_explicit_records(
    async_engine, monkeypatch
) -> None:
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.account_admin.get_app_session_factory", lambda: factory)
    async with factory() as session:
        account = Account(
            id="11111111-1111-4111-8111-111111111111",
            username="alice",
            display_name="Alice",
            password_hash="!test!",
        )
        session.add_all(
            [
                account,
                Conversation(id="legacy-chat", title="Private conversation"),
                Document(
                    id="legacy-doc",
                    filename="private.txt",
                    format="txt",
                    size_bytes=10,
                    storage_path="/tmp/private.txt",
                ),
                Meeting(
                    id="legacy-meeting",
                    consent_policy_version="v1",
                    consent_attested_at=datetime.now(UTC),
                ),
            ]
        )
        await session.commit()

    selected = {
        "conversations": ["legacy-chat"],
        "documents": ["legacy-doc"],
        "meetings": ["legacy-meeting"],
    }
    preview = await _assign_legacy_records("alice", **selected)
    assert all(
        counts == {"selected": 1, "to_assign": 1, "already_assigned": 0}
        for counts in preview.values()
    )

    async with factory() as session:
        assert (await session.get(Conversation, "legacy-chat")).owner_id == LEGACY_ACCOUNT_ID
        assert (await session.get(Document, "legacy-doc")).owner_id == LEGACY_ACCOUNT_ID
        assert (await session.get(Meeting, "legacy-meeting")).owner_id == LEGACY_ACCOUNT_ID

    await _assign_legacy_records("alice", **selected, apply=True)
    async with factory() as session:
        assert (await session.get(Conversation, "legacy-chat")).owner_id == account.id
        assert (await session.get(Document, "legacy-doc")).owner_id == account.id
        assert (await session.get(Meeting, "legacy-meeting")).owner_id == account.id


async def test_legacy_assignment_rejects_records_owned_by_another_account(
    async_engine, monkeypatch
) -> None:
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.account_admin.get_app_session_factory", lambda: factory)
    async with factory() as session:
        session.add_all(
            [
                Account(
                    id="11111111-1111-4111-8111-111111111111",
                    username="alice",
                    display_name="Alice",
                    password_hash="!test!",
                ),
                Account(
                    id="22222222-2222-4222-8222-222222222222",
                    username="bob",
                    display_name="Bob",
                    password_hash="!test!",
                ),
                Conversation(
                    id="bobs-chat",
                    owner_id="22222222-2222-4222-8222-222222222222",
                    title="Bob's conversation",
                ),
            ]
        )
        await session.commit()

    with pytest.raises(ValueError, match="belong to another account"):
        await _assign_legacy_records("alice", conversations=["bobs-chat"])


async def test_legacy_rag_assignment_is_dry_run_then_registers_collection(
    async_engine, monkeypatch
) -> None:
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.account_admin.get_app_session_factory", lambda: factory)
    async with factory() as session:
        account = Account(
            id="11111111-1111-4111-8111-111111111111",
            username="alice",
            display_name="Alice",
            password_hash="!test!",
        )
        session.add(account)
        await session.commit()

    capabilities = CollectionCapabilities(mode="hybrid")
    with patch(
        "app.services.hybrid_vector_store.hybrid_vector_store_service.collection_capabilities",
        new_callable=AsyncMock,
        return_value=capabilities,
    ):
        preview = await _assign_legacy_records("alice", rag_collections=["old_manuals"])
        assert preview["rag_collections"] == {
            "selected": 1,
            "to_assign": 1,
            "already_assigned": 0,
        }
        async with factory() as session:
            assert await session.get(RagCollection, "old_manuals") is None

        await _assign_legacy_records("alice", rag_collections=["old_manuals"], apply=True)

    async with factory() as session:
        registry = await session.get(RagCollection, "old_manuals")
        assert registry is not None and registry.owner_id == account.id


async def test_legacy_rag_assignment_rejects_shared_loader_collection(
    async_engine, monkeypatch
) -> None:
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.account_admin.get_app_session_factory", lambda: factory)
    async with factory() as session:
        session.add(
            Account(
                id="11111111-1111-4111-8111-111111111111",
                username="alice",
                display_name="Alice",
                password_hash="!test!",
            )
        )
        await session.commit()

    capabilities = CollectionCapabilities(mode="hybrid", loader_owned=True)
    with (
        patch(
            "app.services.hybrid_vector_store.hybrid_vector_store_service.collection_capabilities",
            new_callable=AsyncMock,
            return_value=capabilities,
        ),
        pytest.raises(ValueError, match="shared and cannot be assigned"),
    ):
        await _assign_legacy_records("alice", rag_collections=["loader_docs"], apply=True)

    async with factory() as session:
        assert await session.get(RagCollection, "loader_docs") is None
