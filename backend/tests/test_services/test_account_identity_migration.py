"""Legacy data remains intact and quarantined during account migration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command
from app.config import settings
from app.models.db_models import LEGACY_ACCOUNT_ID

if TYPE_CHECKING:
    import pytest


def test_upgrade_quarantines_existing_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing rows get a disabled owner without losing their original content."""
    database_path = tmp_path / "account-identity.db"
    monkeypatch.setattr(settings, "app_database_url", f"sqlite:///{database_path}")
    alembic_dir = Path(__file__).resolve().parents[2] / "alembic"
    config = Config(str(alembic_dir.parent / "alembic.ini"))
    config.set_main_option("script_location", str(alembic_dir))

    command.upgrade(config, "20261012_04")
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text(
                "INSERT INTO conversations (id, title, created_at, updated_at) "
                "VALUES ('legacy-chat', 'Keep this title', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO documents (id, filename, format, size_bytes, storage_path, status, "
                "word_count, created_at, updated_at) VALUES ('legacy-doc', 'notes.txt', 'txt', "
                "12, '/old/notes.txt', 'pending', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO meetings (id, status, consent_policy_version, consent_attested_at, "
                "created_at, updated_at) VALUES ('legacy-meeting', 'created', 'v1', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )

    command.upgrade(config, "20261012_06")
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text(
                "INSERT INTO account_sessions "
                "(id, account_id, token_hash, csrf_token_hash, expires_at, created_at) "
                "VALUES ('legacy-session', :owner_id, :token_hash, :csrf_hash, "
                "datetime('now', '+1 day'), CURRENT_TIMESTAMP)"
            ),
            {
                "owner_id": LEGACY_ACCOUNT_ID,
                "token_hash": "a" * 64,
                "csrf_hash": "b" * 64,
            },
        )

    command.upgrade(config, "head")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        account = connection.execute(
            text("SELECT is_enabled FROM accounts WHERE id = :id"), {"id": LEGACY_ACCOUNT_ID}
        ).scalar_one()
        rows = {
            table: connection.execute(text(f"SELECT id, owner_id FROM {table}")).one()
            for table in ("conversations", "documents", "meetings")
        }
        session = connection.execute(
            text("SELECT csrf_token, revoked_at FROM account_sessions WHERE id = 'legacy-session'")
        ).one()
        ticket_columns = {
            column[1]
            for column in connection.execute(text("PRAGMA table_info(meeting_stream_tickets)"))
        }
        conversation_columns = {
            column[1] for column in connection.execute(text("PRAGMA table_info(conversations)"))
        }
        outbox_columns = {
            column[1]
            for column in connection.execute(text("PRAGMA table_info(memory_outbox_jobs)"))
        }
        recall_summary_columns = {
            column[1]
            for column in connection.execute(
                text("PRAGMA table_info(conversation_recall_summaries)")
            )
        }
        cleanup_columns = {
            column[1]
            for column in connection.execute(text("PRAGMA table_info(memory_vector_cleanup_jobs)"))
        }
        recall_excluded = connection.execute(
            text("SELECT exclude_from_memory FROM conversations WHERE id = 'legacy-chat'")
        ).scalar_one()

    assert account == 0
    assert rows == {
        "conversations": ("legacy-chat", LEGACY_ACCOUNT_ID),
        "documents": ("legacy-doc", LEGACY_ACCOUNT_ID),
        "meetings": ("legacy-meeting", LEGACY_ACCOUNT_ID),
    }
    assert session.csrf_token == "!reauthentication-required!"
    assert session.revoked_at is not None
    assert {"token_hash", "meeting_id", "session_id", "expires_at"} <= ticket_columns
    assert {
        "summary",
        "summary_through_message_id",
        "summary_message_count",
        "summary_revision",
    } <= conversation_columns
    assert recall_excluded == 0
    assert {
        "owner_id",
        "conversation_id",
        "source_message_id",
        "memory_epoch",
        "status",
        "attempts",
        "available_at",
        "lease_until",
    } <= outbox_columns
    assert {
        "owner_id",
        "conversation_id",
        "source_message_id",
        "memory_epoch",
        "revision",
        "content",
    } <= recall_summary_columns
    assert {"owner_id", "conversation_id", "status", "attempts", "available_at"} <= cleanup_columns
