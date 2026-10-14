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

    async def test_stop_completes_after_consumer_failure_with_queued_audio(self) -> None:
        processor = MeetingAudioProcessor(max_queue_size=2)
        consumer_started = asyncio.Event()
        fail_consumer = asyncio.Event()

        async def fail_after_queueing(
            header: AudioEnvelopeHeader, payload: bytes, offset_ms: int, final: bool
        ) -> None:
            consumer_started.set()
            await fail_consumer.wait()
            raise RuntimeError("transcript persistence failed")

        await processor.start(
            "meeting-1", "session-1", consumer=fail_after_queueing, window_ms=1
        )
        timestamp = int(datetime.now(UTC).timestamp() * 1_000_000_000)
        payload = b"\0" * 16
        await processor.accept("meeting-1", "session-1", _header("meeting-1", 0, timestamp), payload)
        await consumer_started.wait()
        await processor.accept(
            "meeting-1", "session-1", _header("meeting-1", 1, timestamp + 1), payload
        )
        fail_consumer.set()

        try:
            await asyncio.wait_for(processor.stop("meeting-1", "session-1"), timeout=0.1)
        finally:
            await processor.purge("meeting-1", "session-1")

    async def test_stop_discards_partial_buffers_when_final_flush_fails(self) -> None:
        processor = MeetingAudioProcessor()

        async def fail_on_final_flush(
            header: AudioEnvelopeHeader, payload: bytes, offset_ms: int, final: bool
        ) -> None:
            raise RuntimeError("final transcript persistence failed")

        session = await processor.start(
            "meeting-final", "session-final", consumer=fail_on_final_flush, window_ms=2
        )
        timestamp = int(datetime.now(UTC).timestamp() * 1_000_000_000)
        await processor.accept(
            "meeting-final",
            "session-final",
            _header("meeting-final", 0, timestamp),
            b"\0" * 16,
        )

        await asyncio.wait_for(processor.stop("meeting-final", "session-final"), timeout=0.1)

        assert session.state.value == "failed"
        assert session.buffers == {}
        assert session.worker is None

    async def test_reconnect_continues_offsets_until_timeline_is_reset(self) -> None:
        processor = MeetingAudioProcessor()
        offsets: list[int] = []

        async def collect_offsets(
            header: AudioEnvelopeHeader, payload: bytes, offset_ms: int, final: bool
        ) -> None:
            offsets.append(offset_ms)

        payload = b"\0" * 16
        await processor.start(
            "meeting-reconnect", "session-first", consumer=collect_offsets, window_ms=1
        )
        first_timestamp = int(datetime.now(UTC).timestamp() * 1_000_000_000)
        for sequence in range(2):
            await processor.accept(
                "meeting-reconnect",
                "session-first",
                _header("meeting-reconnect", sequence, first_timestamp + sequence),
                payload,
            )
        await processor.stop("meeting-reconnect", "session-first")
        await processor.purge("meeting-reconnect", "session-first")

        await processor.start(
            "meeting-reconnect", "session-second", consumer=collect_offsets, window_ms=1
        )
        await processor.accept(
            "meeting-reconnect",
            "session-second",
            _header("meeting-reconnect", 0, first_timestamp + 2),
            payload,
        )
        await processor.stop("meeting-reconnect", "session-second")

        assert offsets == [0, 1, 2]

        await processor.purge("meeting-reconnect", "session-second")
        await processor.reset_timeline("meeting-reconnect")

    async def test_reconnect_offsets_use_elapsed_time_when_sample_rate_changes(self) -> None:
        processor = MeetingAudioProcessor()
        offsets: list[int] = []

        async def collect_offsets(
            header: AudioEnvelopeHeader, payload: bytes, offset_ms: int, final: bool
        ) -> None:
            offsets.append(offset_ms)

        for session_id, sample_rate_hz in (("session-first", 8_000), ("session-second", 16_000)):
            await processor.start(
                "meeting-rate-change", session_id, consumer=collect_offsets, window_ms=1_000
            )
            header = _header("meeting-rate-change", 0, sample_rate_hz)
            header = header.model_copy(
                update={
                    "sample_rate_hz": sample_rate_hz,
                    "frame_count": sample_rate_hz,
                    "duration_ms": 1_000,
                }
            )
            await processor.accept(
                "meeting-rate-change",
                session_id,
                header,
                b"\0" * sample_rate_hz * 2,
            )
            await processor.stop("meeting-rate-change", session_id)
            await processor.purge("meeting-rate-change", session_id)

        assert offsets == [0, 1_000]
        await processor.reset_timeline("meeting-rate-change")
