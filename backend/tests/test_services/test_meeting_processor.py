"""Tests for bounded, session-aware audio processing."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.api.middleware.error_handler import MeetingProtocolError
from app.models.enums import AudioSource
from app.models.schemas import AudioEnvelopeHeader
from app.services.meeting_processor import MeetingAudioProcessor


def _header(meeting_id: str, sequence: int, timestamp_ns: int) -> AudioEnvelopeHeader:
    """Create a valid protocol header for processor tests."""
    return AudioEnvelopeHeader(
        protocol="meeting-audio.v1",
        meeting_id=meeting_id,
        source=AudioSource.SYSTEM,
        sequence=sequence,
        timestamp_ns=timestamp_ns,
        sample_rate_hz=8_000,
        channels=1,
        encoding="pcm_s16le",
        frame_count=8,
        duration_ms=1,
    )


class TestMeetingAudioProcessor:
    async def test_duplicate_retry_is_idempotent_and_sequence_is_per_source(self):
        processor = MeetingAudioProcessor(max_queue_size=2)
        await processor.start("meeting-1", "session-1")
        header = _header("meeting-1", 0, int(datetime.now(UTC).timestamp() * 1_000_000_000))
        payload = b"\0" * 16

        assert await processor.accept("meeting-1", "session-1", header, payload) is False
        assert await processor.accept("meeting-1", "session-1", header, payload) is True
        with pytest.raises(MeetingProtocolError, match="Expected system sequence 1"):
            await processor.accept("meeting-1", "session-1", _header("meeting-1", 2, header.timestamp_ns + 1), payload)

    async def test_second_session_is_rejected_and_purge_removes_state(self):
        processor = MeetingAudioProcessor()
        await processor.start("meeting-1", "session-1")
        with pytest.raises(MeetingProtocolError, match="already active"):
            await processor.start("meeting-1", "session-2")

        await processor.stop("meeting-1", "session-1")
        await processor.purge("meeting-1", "session-1")
        await processor.start("meeting-1", "session-2")
        await processor.fail("meeting-1", "session-2", "test failure")
        await processor.purge("meeting-1", "session-2")

    async def test_backpressure_and_retry_history_are_bounded(self):
        processor = MeetingAudioProcessor(max_queue_size=1)
        await processor.start("meeting-1", "session-1")
        base_timestamp = int(datetime.now(UTC).timestamp() * 1_000_000_000)
        payload = b"\0" * 16

        await processor.accept(
            "meeting-1", "session-1", _header("meeting-1", 0, base_timestamp), payload
        )
        with pytest.raises(MeetingProtocolError, match="queue is full"):
            await processor.accept(
                "meeting-1", "session-1", _header("meeting-1", 1, base_timestamp + 1), payload
            )

        # A larger queue lets us verify the bounded retry metadata independently.
        processor = MeetingAudioProcessor(max_queue_size=32)
        session = await processor.start("meeting-2", "session-2")
        for sequence in range(processor.RETRY_WINDOW + 1):
            await processor.accept(
                "meeting-2",
                "session-2",
                _header("meeting-2", sequence, base_timestamp + sequence),
                payload,
            )
        assert sum(len(history) for history in session.fingerprint_order.values()) == processor.RETRY_WINDOW
        assert len(session.fingerprints) == processor.RETRY_WINDOW

    async def test_stop_serializes_with_accept(self):
        processor = MeetingAudioProcessor(max_queue_size=4)
        await processor.start("meeting-1", "session-1")
        payload = b"\0" * 16
        timestamp = int(datetime.now(UTC).timestamp() * 1_000_000_000)

        results = await asyncio.gather(
            processor.accept("meeting-1", "session-1", _header("meeting-1", 0, timestamp), payload),
            processor.stop("meeting-1", "session-1"),
            return_exceptions=True,
        )
        assert any(result is False or isinstance(result, MeetingProtocolError) for result in results)
        with pytest.raises(MeetingProtocolError, match="no longer active"):
            await processor.accept(
                "meeting-1", "session-1", _header("meeting-1", 1, timestamp + 1), payload
            )
