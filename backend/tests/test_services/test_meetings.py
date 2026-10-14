"""Focused tests for the hardened meeting lifecycle and processor boundary."""

from __future__ import annotations

import asyncio
import json
import struct
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api.middleware.error_handler import ConsentRequiredError, MeetingProtocolError
from app.models.db_models import LEGACY_ACCOUNT_ID, DetectedQuestion, Meeting, TranscriptSegment
from app.models.enums import AudioSource, MeetingStatus
from app.models.schemas import (
    AudioEnvelopeError,
    AudioEnvelopeHeader,
    MeetingStartCommand,
    decode_audio_envelope,
)
from app.services.meetings import MeetingService
from app.services.meeting_answers import MeetingAnswerService
from app.services.transcription import FakeTranscriptionEngine, TranscriptionChunk


def _header(meeting_id: str, sequence: int, source: AudioSource = AudioSource.MICROPHONE):
    """Build a valid one-millisecond, 8 kHz mono PCM header."""
    return AudioEnvelopeHeader(
        protocol="meeting-audio.v1",
        meeting_id=meeting_id,
        source=source,
        sequence=sequence,
        timestamp_ns=int(datetime.now(UTC).timestamp() * 1_000_000_000),
        sample_rate_hz=8_000,
        channels=1,
        encoding="pcm_s16le",
        frame_count=8,
        duration_ms=1,
    )


def _binary_frame(meeting_id: str, sequence: int = 0) -> bytes:
    """Build the canonical binary envelope for decoder tests."""
    header = _header(meeting_id, sequence).model_dump(mode="json")
    encoded = json.dumps(header, separators=(",", ":")).encode("utf-8")
    payload = b"\0" * 16
    return struct.pack(">I", len(encoded)) + encoded + payload


async def _wait_for_transcription_calls(engine: Any, count: int) -> None:
    """Wait until the independent audio worker has processed enough windows."""
    while len(engine.calls) < count:
        await asyncio.sleep(0)


class TestMeetingProtocol:
    def test_binary_envelope_is_bounded_and_strict(self):
        header, payload = decode_audio_envelope(_binary_frame("meeting-1"), "meeting-1")

        assert header.source == AudioSource.MICROPHONE
        assert len(payload) == 16
        with pytest.raises(AudioEnvelopeError, match="does not match"):
            decode_audio_envelope(_binary_frame("meeting-1"), "other-meeting")

    def test_control_protocol_forbids_extra_fields(self):
        with pytest.raises(ValidationError):
            MeetingStartCommand(type="start", unexpected=True)

    def test_duration_is_informational_not_payload_size_authority(self):
        header = AudioEnvelopeHeader(
            protocol="meeting-audio.v1",
            meeting_id="meeting-1",
            source=AudioSource.MICROPHONE,
            sequence=0,
            timestamp_ns=99,
            sample_rate_hz=48_000,
            channels=1,
            encoding="pcm_s16le",
            frame_count=2,
            duration_ms=1,
        )
        encoded = json.dumps(header.model_dump(mode="json"), separators=(",", ":")).encode()
        envelope = struct.pack(">I", len(encoded)) + encoded + b"\0" * 4

        decoded, payload = decode_audio_envelope(envelope, "meeting-1")
        assert decoded.frame_count == 2
        assert decoded.duration_ms == 1
        assert len(payload) == 4


class TestMeetingService:
    async def test_consent_receipt_is_required(self, db_session):
        service = MeetingService(transcription_engine=FakeTranscriptionEngine())

        with pytest.raises(ConsentRequiredError):
            await service.create_meeting(
                db_session,
                owner_id=LEGACY_ACCOUNT_ID,
                consent_policy_version="",
                consent_attested_at=datetime.now(UTC),
            )

        assert await db_session.scalar(select(func.count(Meeting.id))) == 0

    async def test_authoritative_start_and_audio_sequence_idempotency(self, db_session):
        service = MeetingService(transcription_engine=FakeTranscriptionEngine())
        meeting = await service.create_meeting(
            db_session,
            owner_id=LEGACY_ACCOUNT_ID,
            consent_policy_version="meeting-consent-v1",
            consent_attested_at=datetime.now(UTC),
        )
        session_id = "session-1"
        assert meeting.status == MeetingStatus.CREATED.value
        assert meeting.started_at is None

        with pytest.raises(MeetingProtocolError, match="only after start"):
            await service.accept_audio(
                db_session, meeting.id, session_id, _header(meeting.id, 0), b"\0" * 16
            )

        await service.claim_stream(db_session, meeting.id, session_id)
        started = await service.start_stream(db_session, meeting.id, session_id)
        assert started.status == MeetingStatus.ACTIVE.value
        assert started.started_at is not None
        first_header = _header(meeting.id, 0)
        accepted = await service.accept_audio(
            db_session, meeting.id, session_id, first_header, b"\0" * 16
        )
        duplicate = await service.accept_audio(
            db_session, meeting.id, session_id, first_header, b"\0" * 16
        )
        assert accepted is False
        assert duplicate is True

        with pytest.raises(MeetingProtocolError, match="Expected microphone sequence 1"):
            await service.accept_audio(
                db_session, meeting.id, session_id, _header(meeting.id, 2), b"\0" * 16
            )

    async def test_start_rejects_unready_required_asr(self, db_session):
        class UnreadyEngine(FakeTranscriptionEngine):
            async def load(self):
                raise RuntimeError("model is unavailable")

        service = MeetingService(transcription_engine=UnreadyEngine())
        meeting = await service.create_meeting(
            db_session,
            owner_id=LEGACY_ACCOUNT_ID,
            consent_policy_version="v1",
            consent_attested_at=datetime.now(UTC),
        )
        await service.claim_stream(db_session, meeting.id, "session-1")

        with pytest.raises(MeetingProtocolError) as error:
            await service.start_stream(db_session, meeting.id, "session-1")

        assert error.value.code == "ASR_NOT_READY"
        assert meeting.status == MeetingStatus.CREATED.value
        assert meeting.id not in service.processor._sessions
        await service.disconnect_stream(meeting.id, "session-1")

    async def test_transcript_timestamps_continue_across_pcm_windows(self, db_session, monkeypatch):
        monkeypatch.setattr("app.services.meetings.settings.meeting_pcm_window_ms", 1)
        service = MeetingService(
            transcription_engine=FakeTranscriptionEngine(
                [TranscriptionChunk("windowed speech", start_ms=100, end_ms=200)]
            )
        )
        meeting = await service.create_meeting(
            db_session,
            owner_id=LEGACY_ACCOUNT_ID,
            consent_policy_version="v1",
            consent_attested_at=datetime.now(UTC),
        )
        await service.claim_stream(db_session, meeting.id, "session-1")
        await service.start_stream(db_session, meeting.id, "session-1")
        base_timestamp = int(datetime.now(UTC).timestamp() * 1_000_000_000)

        for sequence in range(2):
            header = _header(meeting.id, sequence)
            header = header.model_copy(update={"timestamp_ns": base_timestamp + sequence})
            await service.accept_audio(db_session, meeting.id, "session-1", header, b"\0" * 16)

        await asyncio.wait_for(
            _wait_for_transcription_calls(service.transcription_engine, 2), timeout=1
        )
        await service.stop_meeting(db_session, meeting.id)

        segments = list(
            (
                await db_session.scalars(
                    select(TranscriptSegment)
                    .where(TranscriptSegment.meeting_id == meeting.id)
                    .order_by(TranscriptSegment.sequence)
                )
            ).all()
        )
        assert [(segment.start_ms, segment.end_ms) for segment in segments] == [
            (100, 200),
            (101, 201),
        ]

    async def test_slow_answer_provider_does_not_block_transcription(self, db_session, monkeypatch):
        started = asyncio.Event()

        class SlowAnswerGenerator:
            async def generate(self, question: str, context: str) -> str:
                started.set()
                await asyncio.sleep(1)
                return "slow answer"

        monkeypatch.setattr("app.services.meetings.settings.meeting_pcm_window_ms", 1)
        service = MeetingService(
            transcription_engine=FakeTranscriptionEngine(
                [TranscriptionChunk("What is next?")]
            ),
            answer_service=MeetingAnswerService(
                generator=SlowAnswerGenerator(),
                provider_timeout_seconds=0.05,
            ),
        )
        meeting = await service.create_meeting(
            db_session,
            owner_id=LEGACY_ACCOUNT_ID,
            consent_policy_version="v1",
            consent_attested_at=datetime.now(UTC),
        )
        await service.claim_stream(db_session, meeting.id, "session-1")
        await service.start_stream(db_session, meeting.id, "session-1")
        queue = service.event_queue(meeting.id, "session-1")

        await service.accept_audio(
            db_session,
            meeting.id,
            "session-1",
            _header(meeting.id, 0, AudioSource.SYSTEM),
            b"\0" * 16,
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        await service.accept_audio(
            db_session,
            meeting.id,
            "session-1",
            _header(meeting.id, 1, AudioSource.SYSTEM),
            b"\0" * 16,
        )

        await asyncio.wait_for(
            _wait_for_transcription_calls(service.transcription_engine, 2), timeout=1
        )
        first_events = [await asyncio.wait_for(queue.get(), timeout=1) for _ in range(4)]
        assert [event["type"] for event in first_events[:3]] == [
            "transcript",
            "question",
            "transcript",
        ]
        await service.stop_meeting(db_session, meeting.id)

    async def test_stop_is_idempotent_and_cleans_processor(self, db_session):
        service = MeetingService(transcription_engine=FakeTranscriptionEngine())
        meeting = await service.create_meeting(
            db_session,
            owner_id=LEGACY_ACCOUNT_ID,
            consent_policy_version="v1",
            consent_attested_at=datetime.now(UTC),
        )
        await service.claim_stream(db_session, meeting.id, "session-1")
        await service.start_stream(db_session, meeting.id, "session-1")

        stopped = await service.stop_meeting(db_session, meeting.id)
        stopped_at = stopped.stopped_at
        stopped_again = await service.stop_meeting(db_session, meeting.id)

        assert stopped_again.status == MeetingStatus.STOPPED.value
        assert stopped_again.stopped_at == stopped_at
        assert meeting.id not in service._sessions

    async def test_delete_cascades_transcript_and_questions(self, db_session):
        service = MeetingService(transcription_engine=FakeTranscriptionEngine())
        meeting = await service.create_meeting(
            db_session,
            owner_id=LEGACY_ACCOUNT_ID,
            consent_policy_version="v1",
            consent_attested_at=datetime.now(UTC),
        )
        segment = TranscriptSegment(meeting_id=meeting.id, sequence=0, text="question")
        db_session.add(segment)
        await db_session.flush()
        db_session.add(
            DetectedQuestion(
                meeting_id=meeting.id,
                transcript_segment_id=segment.id,
                question="What is next?",
            )
        )
        await db_session.commit()

        await service.delete_meeting(db_session, meeting.id)

        assert await db_session.scalar(select(Meeting).where(Meeting.id == meeting.id)) is None
        assert await db_session.scalar(
            select(func.count(TranscriptSegment.id)).where(TranscriptSegment.meeting_id == meeting.id)
        ) == 0
        assert await db_session.scalar(
            select(func.count(DetectedQuestion.id)).where(DetectedQuestion.meeting_id == meeting.id)
        ) == 0
