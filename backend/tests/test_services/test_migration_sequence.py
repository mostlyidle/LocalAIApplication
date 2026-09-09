"""Upgrade coverage for the durable meeting transcript sequence counter."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from alembic import command
from app.config import settings
from app.models.db_models import TranscriptSegment
from app.services.meetings import MeetingService


@pytest.fixture
def upgraded_from_02(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a database at revision 02, seed transcripts, and upgrade to head."""
    database_path = tmp_path / "meeting-sequence.db"
    monkeypatch.setattr(settings, "app_database_url", f"sqlite:///{database_path}")
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))

    command.upgrade(config, "20260909_02")
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        created_at = datetime.now(UTC)
        connection.execute(
            text(
                "INSERT INTO meetings "
                "(id, status, consent_policy_version, consent_attested_at, started_at, "
                "stopped_at, failed_at, failure_reason, created_at, updated_at) "
                "VALUES (:id, 'created', 'v1', :created_at, NULL, NULL, NULL, NULL, "
                ":created_at, :created_at)"
            ),
            {"id": "meeting-with-transcript", "created_at": created_at},
        )
        connection.execute(
            text(
                "INSERT INTO meetings "
                "(id, status, consent_policy_version, consent_attested_at, started_at, "
                "stopped_at, failed_at, failure_reason, created_at, updated_at) "
                "VALUES (:id, 'created', 'v1', :created_at, NULL, NULL, NULL, NULL, "
                ":created_at, :created_at)"
            ),
            {"id": "meeting-without-transcript", "created_at": created_at},
        )
        connection.execute(
            text(
                "INSERT INTO transcript_segments "
                "(id, meeting_id, sequence, source, speaker, text, created_at) "
                "VALUES (:id, :meeting_id, :sequence, 'system', 'system', :text, :created_at)"
            ),
            {
                "id": "segment-zero",
                "meeting_id": "meeting-with-transcript",
                "sequence": 0,
                "text": "first",
                "created_at": created_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO transcript_segments "
                "(id, meeting_id, sequence, source, speaker, text, created_at) "
                "VALUES (:id, :meeting_id, :sequence, 'microphone', 'microphone', :text, :created_at)"
            ),
            {
                "id": "segment-four",
                "meeting_id": "meeting-with-transcript",
                "sequence": 4,
                "text": "fifth",
                "created_at": created_at,
            },
        )

    command.upgrade(config, "head")
    return database_path


async def test_upgrade_backfills_existing_and_empty_meeting_sequences(upgraded_from_02: Path):
    """The first post-upgrade allocation follows existing rows without collision."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{upgraded_from_02}")
    async with AsyncSession(engine, expire_on_commit=False) as session:
        with_transcript = await MeetingService._allocate_transcript_sequence(
            session, "meeting-with-transcript"
        )
        without_transcript = await MeetingService._allocate_transcript_sequence(
            session, "meeting-without-transcript"
        )
        await session.commit()

        session.add(
            TranscriptSegment(
                id="segment-five",
                meeting_id="meeting-with-transcript",
                sequence=with_transcript,
                source="system",
                text="sixth",
            )
        )
        session.add(
            TranscriptSegment(
                id="segment-empty-zero",
                meeting_id="meeting-without-transcript",
                sequence=without_transcript,
                source="system",
                text="first",
            )
        )
        await session.commit()
    await engine.dispose()

    assert with_transcript == 5
    assert without_transcript == 0
