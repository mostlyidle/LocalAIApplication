"""Fake-engine-focused Phase 2 transcription and answer tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select

from app.api.middleware.error_handler import MeetingProtocolError
from app.models.db_models import LEGACY_ACCOUNT_ID, DetectedQuestion, Meeting, TranscriptSegment
from app.models.enums import AudioSource, MeetingStatus
from app.models.schemas import AudioEnvelopeHeader, MeetingServerEvent
from app.services.meeting_answers import FakeAnswerGenerator, MeetingAnswerService
from app.services.meetings import INTERRUPTED_MEETING_REASON, MeetingService
from app.services.transcription import FakeTranscriptionEngine, TranscriptionChunk


def _header(
    meeting_id: str,
    source: AudioSource,
    sequence: int = 0,
) -> AudioEnvelopeHeader:
    """Build a small valid PCM window for the fake engine."""
    return AudioEnvelopeHeader(
        protocol="meeting-audio.v1",
        meeting_id=meeting_id,
        source=source,
        sequence=sequence,
        timestamp_ns=int(datetime.now(UTC).timestamp() * 1_000_000_000) + sequence,
        sample_rate_hz=8_000,
        channels=1,
        encoding="pcm_s16le",
        frame_count=8,
        duration_ms=1,
    )


async def _read_events(queue, count: int) -> list[dict]:
    """Read a deterministic number of inference events."""
    return [await asyncio.wait_for(queue.get(), timeout=1) for _ in range(count)]


async def test_fake_engine_persists_system_transcript_question_and_answer(db_session):
    engine = FakeTranscriptionEngine([TranscriptionChunk("What is the launch date?")])
    answer_generator = FakeAnswerGenerator("The local answer")
    service = MeetingService(
        transcription_engine=engine,
        answer_service=MeetingAnswerService(generator=answer_generator),
    )
    meeting = await service.create_meeting(
        db_session,
        owner_id=LEGACY_ACCOUNT_ID,
        consent_policy_version="v1",
        consent_attested_at=datetime.now(UTC),
    )
    await service.claim_stream(db_session, meeting.id, "session")
    await service.start_stream(db_session, meeting.id, "session")
    queue = service.event_queue(meeting.id, "session")

    await service.accept_audio(
        db_session,
        meeting.id,
        "session",
        _header(meeting.id, AudioSource.SYSTEM),
        b"\0" * 16,
    )
    await service.source_ended(meeting.id, "session", AudioSource.SYSTEM)
    events = await _read_events(queue, 3)

    assert [event["type"] for event in events] == ["transcript", "question", "answer"]
    assert events[0]["source"] == "system"
    assert events[1]["text"] == "What is the launch date?"
    assert events[2]["answer"] == "The local answer"
    assert answer_generator.calls == [("What is the launch date?", "")]
    assert len(engine.calls) == 1
    assert TypeAdapter(MeetingServerEvent).validate_python(events[0]).type == "transcript"
    with pytest.raises(ValidationError):
        TypeAdapter(MeetingServerEvent).validate_python({**events[0], "unexpected": True})

    assert await db_session.scalar(select(func.count(TranscriptSegment.id))) == 1
    assert await db_session.scalar(select(func.count(DetectedQuestion.id))) == 1
    segment = await db_session.scalar(select(TranscriptSegment))
    assert segment.source == "system"
    assert segment.text == "What is the launch date?"
    await service.stop_meeting(db_session, meeting.id)


async def test_microphone_transcript_does_not_trigger_question_answer(db_session):
    engine = FakeTranscriptionEngine([TranscriptionChunk("What is the launch date?")])
    answers = FakeAnswerGenerator()
    service = MeetingService(
        transcription_engine=engine,
        answer_service=MeetingAnswerService(generator=answers),
    )
    meeting = await service.create_meeting(
        db_session,
        owner_id=LEGACY_ACCOUNT_ID,
        consent_policy_version="v1",
        consent_attested_at=datetime.now(UTC),
    )
    await service.claim_stream(db_session, meeting.id, "session")
    await service.start_stream(db_session, meeting.id, "session")
    queue = service.event_queue(meeting.id, "session")

    await service.accept_audio(
        db_session,
        meeting.id,
        "session",
        _header(meeting.id, AudioSource.MICROPHONE),
        b"\0" * 16,
    )
    await service.source_ended(meeting.id, "session", AudioSource.MICROPHONE)
    event = await asyncio.wait_for(queue.get(), timeout=1)

    assert event["type"] == "transcript"
    assert event["source"] == "microphone"
    assert answers.calls == []
    assert await db_session.scalar(select(func.count(DetectedQuestion.id))) == 0
    await service.stop_meeting(db_session, meeting.id)


async def test_answer_failure_emits_degraded_event_and_fallback_answer(db_session):
    class FailingAnswerGenerator:
        async def generate(self, question: str, context: str) -> str:
            raise RuntimeError("Ollama is unavailable")

    service = MeetingService(
        transcription_engine=FakeTranscriptionEngine([TranscriptionChunk("What is next?")]),
        answer_service=MeetingAnswerService(generator=FailingAnswerGenerator()),
    )
    meeting = await service.create_meeting(
        db_session,
        owner_id=LEGACY_ACCOUNT_ID,
        consent_policy_version="v1",
        consent_attested_at=datetime.now(UTC),
    )
    await service.claim_stream(db_session, meeting.id, "session")
    await service.start_stream(db_session, meeting.id, "session")
    queue = service.event_queue(meeting.id, "session")

    await service.accept_audio(
        db_session,
        meeting.id,
        "session",
        _header(meeting.id, AudioSource.SYSTEM),
        b"\0" * 16,
    )
    await service.source_ended(meeting.id, "session", AudioSource.SYSTEM)
    events = await _read_events(queue, 4)

    assert [event["type"] for event in events] == [
        "transcript",
        "question",
        "degraded",
        "answer",
    ]
    assert events[2]["component"] == "ollama"
    assert events[3]["answer"] == "No local answer is available."
    await service.stop_meeting(db_session, meeting.id)


async def test_optional_rag_failure_degrades_without_blocking_answer(monkeypatch):
    class FailingRetriever:
        async def search(
            self,
            query: str,
            collection: str | None = None,
            top_k: int | None = None,
            score_threshold: float | None = None,
        ) -> list[dict[str, Any]]:
            raise RuntimeError("Chroma is unavailable")

    monkeypatch.setattr("app.services.meeting_answers.settings.meeting_enable_rag", True)
    generator = FakeAnswerGenerator("Answer without retrieval")
    result = await MeetingAnswerService(
        generator=generator,
        retriever=FailingRetriever(),
    ).suggest("What is next?")

    assert result.answer == "Answer without retrieval"
    assert result.degraded_components == ["rag"]
    assert generator.calls == [("What is next?", "")]


async def test_concurrent_consumers_allocate_persisted_sequences_atomically(db_session):
    service = MeetingService(
        transcription_engine=FakeTranscriptionEngine([TranscriptionChunk("first")]),
        answer_service=MeetingAnswerService(generator=FakeAnswerGenerator()),
    )
    meeting = await service.create_meeting(
        db_session,
        owner_id=LEGACY_ACCOUNT_ID,
        consent_policy_version="v1",
        consent_attested_at=datetime.now(UTC),
    )
    factory = service._session_factory_for(db_session)
    assert service.transcription_engine is not None
    consumer = service._make_consumer(meeting.id, service.transcription_engine, factory)

    await asyncio.gather(
        consumer(_header(meeting.id, AudioSource.MICROPHONE, 0), b"\0" * 16, True),
        consumer(_header(meeting.id, AudioSource.MICROPHONE, 1), b"\0" * 16, True),
    )

    segments = list(
        (
            await db_session.scalars(
                select(TranscriptSegment)
                .where(TranscriptSegment.meeting_id == meeting.id)
                .order_by(TranscriptSegment.sequence)
            )
        ).all()
    )
    assert [segment.sequence for segment in segments] == [0, 1]


async def test_reconnect_continues_sequence_from_persisted_segments(db_session):
    engine = FakeTranscriptionEngine([TranscriptionChunk("persisted")])
    service = MeetingService(
        transcription_engine=engine,
        answer_service=MeetingAnswerService(generator=FakeAnswerGenerator()),
    )
    meeting = await service.create_meeting(
        db_session,
        owner_id=LEGACY_ACCOUNT_ID,
        consent_policy_version="v1",
        consent_attested_at=datetime.now(UTC),
    )

    await service.claim_stream(db_session, meeting.id, "first")
    await service.start_stream(db_session, meeting.id, "first")
    first_queue = service.event_queue(meeting.id, "first")
    await service.accept_audio(
        db_session,
        meeting.id,
        "first",
        _header(meeting.id, AudioSource.MICROPHONE),
        b"\0" * 16,
    )
    await service.source_ended(meeting.id, "first", AudioSource.MICROPHONE)
    await _read_events(first_queue, 1)
    await service.disconnect_stream(meeting.id, "first")

    await service.claim_stream(db_session, meeting.id, "second")
    await service.start_stream(db_session, meeting.id, "second")
    second_queue = service.event_queue(meeting.id, "second")
    await service.accept_audio(
        db_session,
        meeting.id,
        "second",
        _header(meeting.id, AudioSource.MICROPHONE),
        b"\0" * 16,
    )
    await service.source_ended(meeting.id, "second", AudioSource.MICROPHONE)
    await _read_events(second_queue, 1)

    segments = list(
        (
            await db_session.scalars(
                select(TranscriptSegment)
                .where(TranscriptSegment.meeting_id == meeting.id)
                .order_by(TranscriptSegment.sequence)
            )
        ).all()
    )
    assert [segment.sequence for segment in segments] == [0, 1]
    assert service.processor._sessions[meeting.id].session_id == "second"
    await service.stop_meeting(db_session, meeting.id)


async def test_disconnect_aborts_long_inference_before_reconnect(db_session):
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowEngine(FakeTranscriptionEngine):
        async def transcribe(self, *args, **kwargs):
            started.set()
            await release.wait()
            return []

    service = MeetingService(transcription_engine=SlowEngine())
    meeting = await service.create_meeting(
        db_session,
        owner_id=LEGACY_ACCOUNT_ID,
        consent_policy_version="v1",
        consent_attested_at=datetime.now(UTC),
    )
    await service.claim_stream(db_session, meeting.id, "first")
    await service.start_stream(db_session, meeting.id, "first")
    await service.accept_audio(
        db_session,
        meeting.id,
        "first",
        _header(meeting.id, AudioSource.MICROPHONE),
        b"\0" * 16,
    )
    await service.source_ended(meeting.id, "first", AudioSource.MICROPHONE)
    await asyncio.wait_for(started.wait(), timeout=1)

    await asyncio.wait_for(service.disconnect_stream(meeting.id, "first"), timeout=1)
    assert meeting.id not in service._sessions
    assert meeting.id not in service.processor._sessions

    service.transcription_engine = FakeTranscriptionEngine()
    await service.claim_stream(db_session, meeting.id, "second")
    await service.start_stream(db_session, meeting.id, "second")
    await service.stop_meeting(db_session, meeting.id)
    release.set()


async def test_stop_releases_claim_but_drains_final_events_before_return(db_session):
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowAnswerGenerator:
        async def generate(self, question: str, context: str) -> str:
            started.set()
            await release.wait()
            return "final local answer"

    service = MeetingService(
        transcription_engine=FakeTranscriptionEngine([TranscriptionChunk("What is next?")]),
        answer_service=MeetingAnswerService(generator=SlowAnswerGenerator()),
    )
    meeting = await service.create_meeting(
        db_session,
        owner_id=LEGACY_ACCOUNT_ID,
        consent_policy_version="v1",
        consent_attested_at=datetime.now(UTC),
    )
    await service.claim_stream(db_session, meeting.id, "session")
    await service.start_stream(db_session, meeting.id, "session")
    queue = service.event_queue(meeting.id, "session")
    await service.accept_audio(
        db_session,
        meeting.id,
        "session",
        _header(meeting.id, AudioSource.SYSTEM),
        b"\0" * 16,
    )
    await service.source_ended(meeting.id, "session", AudioSource.SYSTEM)

    stop_task = asyncio.create_task(service.stop_meeting(db_session, meeting.id))
    await asyncio.wait_for(started.wait(), timeout=1)
    await asyncio.sleep(0)
    assert meeting.id not in service._sessions
    assert not stop_task.done()
    assert meeting.status == "stopped"

    with pytest.raises(MeetingProtocolError, match="session is closing"):
        await service.claim_stream(db_session, meeting.id, "reconnect")

    release.set()
    await stop_task
    events = await _read_events(queue, 3)
    assert [event["type"] for event in events] == ["transcript", "question", "answer"]


async def test_reconcile_active_meetings_fails_stale_meeting_without_deleting_transcript(
    db_session,
):
    """A restart closes stale state while retaining the durable meeting history."""
    meeting = Meeting(
        status=MeetingStatus.ACTIVE.value,
        consent_policy_version="v1",
        consent_attested_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
    )
    db_session.add(meeting)
    await db_session.flush()
    db_session.add(
        TranscriptSegment(
            meeting_id=meeting.id,
            sequence=0,
            source=AudioSource.SYSTEM.value,
            speaker=AudioSource.SYSTEM.value,
            text="Persisted before restart",
        )
    )
    await db_session.commit()

    service = MeetingService()
    assert await service.reconcile_active_meetings(db_session) == 1
    await db_session.refresh(meeting)

    assert meeting.status == MeetingStatus.FAILED.value
    assert meeting.failed_at is not None
    assert meeting.failure_reason == INTERRUPTED_MEETING_REASON
    segment = await db_session.scalar(select(TranscriptSegment))
    assert segment is not None
    assert segment.text == "Persisted before restart"

    assert await service.reconcile_active_meetings(db_session) == 0
