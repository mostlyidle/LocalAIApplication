"""Bounded, session-aware meeting audio processor boundary.

The processor validates and accepts PCM frames into a bounded in-memory queue,
then hands rolling windows to an asynchronous local-processing consumer.  It
never persists raw audio and keeps transport ACKs independent of inference.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from app.api.middleware.error_handler import MeetingProtocolError
from app.models.schemas import MAX_AUDIO_PAYLOAD_BYTES, AudioEnvelopeHeader

if TYPE_CHECKING:
    from app.models.enums import AudioSource


class ProcessorState(StrEnum):
    """Lifecycle state of one claimed audio processor session."""

    ACTIVE = "active"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True)
class AcceptedAudio:
    """One bounded in-memory frame awaiting the local processing consumer."""

    header: AudioEnvelopeHeader
    payload: bytes


@dataclass(frozen=True)
class SourceEndedCommand:
    """Worker command to flush one source's rolling window."""

    source: AudioSource


WindowConsumer = Callable[[AudioEnvelopeHeader, bytes, bool], Awaitable[None]]


@dataclass
class ProcessorSession:
    """Per-WebSocket processor state, including idempotency records."""

    meeting_id: str
    session_id: str
    queue: asyncio.Queue[AcceptedAudio | SourceEndedCommand]
    state: ProcessorState = ProcessorState.ACTIVE
    next_sequence: dict[AudioSource, int] = field(default_factory=dict)
    last_timestamp_ns: dict[AudioSource, int] = field(default_factory=dict)
    last_headers: dict[AudioSource, AudioEnvelopeHeader] = field(default_factory=dict, repr=False)
    fingerprints: dict[tuple[AudioSource, int], str] = field(default_factory=dict)
    fingerprint_order: dict[AudioSource, deque[int]] = field(default_factory=dict)
    ended_sources: set[AudioSource] = field(default_factory=set)
    failure_reason: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    consumer: WindowConsumer | None = field(default=None, repr=False)
    window_ms: int = 2_000
    buffers: dict[AudioSource, bytearray] = field(default_factory=dict, repr=False)
    worker: asyncio.Task[None] | None = field(default=None, repr=False)


class MeetingAudioProcessor:
    """Manage one active bounded processor session per meeting."""

    RETRY_WINDOW = 8

    def __init__(self, max_queue_size: int = 128) -> None:
        if max_queue_size < 1:
            raise ValueError("max_queue_size must be positive")
        self._max_queue_size = max_queue_size
        self._sessions: dict[str, ProcessorSession] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        meeting_id: str,
        session_id: str,
        *,
        consumer: WindowConsumer | None = None,
        window_ms: int = 2_000,
    ) -> ProcessorSession:
        """Claim the sole active stream for a meeting, idempotently."""
        async with self._lock:
            existing = self._sessions.get(meeting_id)
            if existing is not None and existing.state == ProcessorState.ACTIVE:
                if existing.session_id == session_id:
                    return existing
                raise MeetingProtocolError(
                    "Another audio stream is already active for this meeting.",
                    "ACTIVE_AUDIO_SESSION",
                )
            session = ProcessorSession(
                meeting_id=meeting_id,
                session_id=session_id,
                queue=asyncio.Queue(maxsize=self._max_queue_size),
                consumer=consumer,
                window_ms=max(1, window_ms),
            )
            session.worker = asyncio.create_task(self._run_session(session))
            self._sessions[meeting_id] = session
            return session

    async def accept(
        self,
        meeting_id: str,
        session_id: str,
        header: AudioEnvelopeHeader,
        payload: bytes,
    ) -> bool:
        """Accept a frame, returning whether it was an idempotent duplicate."""
        session = self._get_session(meeting_id, session_id)
        async with session.lock:
            self._assert_active(session)
            if header.meeting_id != meeting_id:
                raise MeetingProtocolError("Audio meeting_id does not match the session.", "MEETING_ID_MISMATCH")
            expected_payload_size = header.frame_count * header.channels * 2
            if len(payload) > MAX_AUDIO_PAYLOAD_BYTES or len(payload) != expected_payload_size:
                raise MeetingProtocolError(
                    "PCM payload size does not match frame_count and channels.",
                    "AUDIO_PAYLOAD_SIZE_MISMATCH",
                )
            source = header.source
            if source in session.ended_sources:
                raise MeetingProtocolError(
                    f"Audio source '{source.value}' has ended.", "SOURCE_ALREADY_ENDED"
                )

            key = (source, header.sequence)
            fingerprint = _fingerprint(header, payload)
            expected = session.next_sequence.get(source, 0)
            if header.sequence < expected:
                if session.fingerprints.get(key) == fingerprint:
                    return True
                raise MeetingProtocolError(
                    "Retry is outside the idempotency window or has a different payload.",
                    "SEQUENCE_RETRY_MISMATCH",
                )
            if header.sequence > expected:
                raise MeetingProtocolError(
                    f"Expected {source.value} sequence {expected}, received {header.sequence}.",
                    "OUT_OF_ORDER_AUDIO_SEQUENCE",
                )
            previous_timestamp = session.last_timestamp_ns.get(source)
            if previous_timestamp is not None and header.timestamp_ns <= previous_timestamp:
                raise MeetingProtocolError(
                    "Audio timestamps must increase for each source.",
                    "INVALID_AUDIO_TIMESTAMP",
                )
            if session.queue.full():
                raise MeetingProtocolError(
                    "Audio processor queue is full; retry the frame later.",
                    "AUDIO_PROCESSOR_BACKPRESSURE",
                )

            session.queue.put_nowait(AcceptedAudio(header=header, payload=payload))
            session.fingerprints[key] = fingerprint
            sequence_history = session.fingerprint_order.setdefault(source, deque())
            sequence_history.append(header.sequence)
            while len(sequence_history) > self.RETRY_WINDOW:
                expired_sequence = sequence_history.popleft()
                session.fingerprints.pop((source, expired_sequence), None)
            session.next_sequence[source] = expected + 1
            session.last_timestamp_ns[source] = header.timestamp_ns
            session.last_headers[source] = header
            return False

    async def source_ended(self, meeting_id: str, session_id: str, source: AudioSource) -> None:
        """End one source without stopping other sources or the meeting."""
        session = self._get_session(meeting_id, session_id)
        async with session.lock:
            self._assert_active(session)
            session.ended_sources.add(source)
            try:
                session.queue.put_nowait(SourceEndedCommand(source=source))
            except asyncio.QueueFull as exc:
                raise MeetingProtocolError(
                    "Audio processor queue is full; source end must be retried.",
                    "AUDIO_PROCESSOR_BACKPRESSURE",
                ) from exc

    async def stop(self, meeting_id: str, session_id: str) -> None:
        """Stop and drain a session."""
        session = self._sessions.get(meeting_id)
        if session is None or session.session_id != session_id:
            return
        async with session.lock:
            await session.queue.join()
            await self._flush_all(session)
            if session.state == ProcessorState.ACTIVE:
                session.state = ProcessorState.STOPPED
            _drain(session.queue)
            await self._cancel_worker(session)

    async def abort(self, meeting_id: str, session_id: str) -> None:
        """Cancel a disconnected session without waiting for inference or flushing PCM."""
        session = self._sessions.get(meeting_id)
        if session is None or session.session_id != session_id:
            return
        async with session.lock:
            session.state = ProcessorState.STOPPED
            _drain(session.queue)
            session.buffers.clear()
            await self._cancel_worker(session)

    async def fail(self, meeting_id: str, session_id: str, reason: str) -> None:
        """Fail and drain a session without retaining its audio payloads."""
        session = self._sessions.get(meeting_id)
        if session is None or session.session_id != session_id:
            return
        async with session.lock:
            session.state = ProcessorState.FAILED
            session.failure_reason = reason[:500]
            _drain(session.queue)
            await self._cancel_worker(session)

    async def purge(self, meeting_id: str, session_id: str | None = None) -> None:
        """Remove all session metadata and queued PCM for a meeting."""
        session = self._sessions.get(meeting_id)
        if session is None or (session_id is not None and session.session_id != session_id):
            return
        async with session.lock:
            _drain(session.queue)
            await self._cancel_worker(session)
            if self._sessions.get(meeting_id) is session:
                del self._sessions[meeting_id]

    async def _run_session(self, session: ProcessorSession) -> None:
        """Consume accepted frames into bounded per-source rolling windows."""
        try:
            while True:
                item = await session.queue.get()
                try:
                    if isinstance(item, SourceEndedCommand):
                        await self._flush_source(session, item.source, final=True)
                    else:
                        buffer = session.buffers.setdefault(item.header.source, bytearray())
                        buffer.extend(item.payload)
                        window_bytes = max(
                            item.header.channels * 2,
                            item.header.sample_rate_hz
                            * item.header.channels
                            * 2
                            * session.window_ms
                            // 1_000,
                        )
                        while len(buffer) >= window_bytes:
                            window = bytes(buffer[:window_bytes])
                            del buffer[:window_bytes]
                            await self._consume(session, item.header, window, final=False)
                finally:
                    session.queue.task_done()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            session.state = ProcessorState.FAILED
            session.failure_reason = str(exc)[:500]

    async def _flush_source(self, session: ProcessorSession, source: AudioSource, final: bool) -> None:
        """Send a source's remaining partial rolling window to the consumer."""
        buffer = session.buffers.pop(source, None)
        if not buffer:
            return
        # The source's most recent accepted header supplies format metadata.
        header = session.last_headers.get(source)
        if header is not None:
            await self._consume(session, header, bytes(buffer), final=final)

    async def _flush_all(self, session: ProcessorSession) -> None:
        """Flush all partial windows before terminal cleanup."""
        for source in list(session.buffers):
            await self._flush_source(session, source, final=True)

    async def _consume(
        self,
        session: ProcessorSession,
        header: AudioEnvelopeHeader,
        payload: bytes,
        *,
        final: bool,
    ) -> None:
        """Invoke the optional inference consumer outside the ACK path."""
        if session.consumer is not None:
            await session.consumer(header, payload, final)

    async def _cancel_worker(self, session: ProcessorSession) -> None:
        """Cancel and await the worker without retaining PCM buffers."""
        worker = session.worker
        session.worker = None
        if worker is None or worker is asyncio.current_task():
            return
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker

    def _get_session(self, meeting_id: str, session_id: str) -> ProcessorSession:
        session = self._sessions.get(meeting_id)
        if session is None or session.session_id != session_id:
            raise MeetingProtocolError("Audio session is not active.", "AUDIO_SESSION_NOT_ACTIVE")
        return session

    @staticmethod
    def _assert_active(session: ProcessorSession) -> None:
        if session.state != ProcessorState.ACTIVE:
            raise MeetingProtocolError("Audio session is no longer active.", "AUDIO_SESSION_NOT_ACTIVE")


def _fingerprint(header: AudioEnvelopeHeader, payload: bytes) -> str:
    """Hash frame metadata and PCM for safe idempotent retry detection."""
    metadata = header.model_dump_json().encode("utf-8")
    return hashlib.sha256(metadata + b"\0" + payload).hexdigest()


def _drain(queue: asyncio.Queue[AcceptedAudio | SourceEndedCommand]) -> None:
    """Drop queued PCM without blocking or persisting it."""
    while not queue.empty():
        try:
            queue.get_nowait()
            queue.task_done()
        except asyncio.QueueEmpty:
            return


__all__ = ["AcceptedAudio", "MeetingAudioProcessor", "ProcessorSession", "ProcessorState"]
