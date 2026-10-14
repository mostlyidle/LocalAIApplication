"""Consent-aware meeting lifecycle and audio-session service."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.middleware.error_handler import (
    ConsentRequiredError,
    MeetingProtocolError,
    NotFoundError,
)
from app.config import settings
from app.models.db_models import DetectedQuestion, Meeting, TranscriptSegment
from app.models.enums import MeetingStatus
from app.models.schemas import (
    AudioEnvelopeHeader,
    MeetingAnswerEvent,
    MeetingDegradedEvent,
    MeetingQuestionEvent,
    MeetingTranscriptEvent,
)
from app.services.meeting_answers import (
    ANSWER_PROVIDER_TIMEOUT_SECONDS,
    DeterministicQuestionDetector,
    MeetingAnswerService,
)
from app.services.meeting_processor import MeetingAudioProcessor, WindowConsumer
from app.services.transcription import (
    ASR_READINESS_TIMEOUT_SECONDS,
    TranscriptionEngine,
    get_local_asr_engine,
)

if TYPE_CHECKING:
    from pydantic import BaseModel

    from app.models.enums import AudioSource

logger = structlog.get_logger(__name__)

INTERRUPTED_MEETING_REASON = (
    "Meeting interrupted because the backend process stopped. "
    "Persisted transcript is preserved; audio cannot be recovered. "
    "Start a new meeting to continue."
)
ANSWER_QUEUE_SIZE = 8
ANSWER_DRAIN_GRACE_SECONDS = 0.25


@dataclass(frozen=True)
class PendingMeetingAnswer:
    """One bounded answer request associated with a stream session."""

    question_id: str
    question: str


class MeetingService:
    """Own meeting state transitions and the Phase 2 processor boundary.

    No audio bytes are written to SQL or logs.  The processor only holds a
    bounded in-memory queue and is purged on every terminal lifecycle path.
    """

    def __init__(
        self,
        processor: MeetingAudioProcessor | None = None,
        transcription_engine: TranscriptionEngine | None = None,
        answer_service: MeetingAnswerService | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.processor = processor or MeetingAudioProcessor(
            max_queue_size=settings.meeting_audio_queue_size
        )
        self.transcription_engine = transcription_engine
        if answer_service is None and settings.meeting_enable_rag:
            from app.services.hybrid_vector_store import hybrid_vector_store_service

            answer_service = MeetingAnswerService(retriever=hybrid_vector_store_service)
        self.answer_service = answer_service or MeetingAnswerService()
        self.session_factory = session_factory
        self.question_detector = DeterministicQuestionDetector()
        self._sessions: dict[str, str] = {}
        self._event_queues: dict[str, asyncio.Queue[dict[str, object]]] = {}
        self._answer_queues: dict[str, asyncio.Queue[PendingMeetingAnswer]] = {}
        self._answer_workers: dict[str, asyncio.Task[None]] = {}
        self._answer_sessions: dict[str, str] = {}
        self._asr_ready = False
        self._asr_load_task: asyncio.Task[None] | None = None
        self._closing_meetings: dict[str, asyncio.Event] = {}
        self._session_lock = asyncio.Lock()

    async def create_meeting(
        self,
        db: AsyncSession,
        *,
        owner_id: str,
        consent_policy_version: str,
        consent_attested_at: datetime,
    ) -> Meeting:
        """Create a consented meeting in the ``created`` state."""
        if not consent_policy_version.strip():
            raise ConsentRequiredError()
        if consent_attested_at.tzinfo is None or consent_attested_at.utcoffset() is None:
            raise ConsentRequiredError()

        meeting = Meeting(
            owner_id=owner_id,
            status=MeetingStatus.CREATED.value,
            consent_policy_version=consent_policy_version,
            consent_attested_at=consent_attested_at.astimezone(UTC),
        )
        db.add(meeting)
        await db.commit()
        await db.refresh(meeting)
        logger.info("meeting_created", meeting_id=meeting.id)
        return meeting

    async def get_meeting(
        self, db: AsyncSession, meeting_id: str, owner_id: str | None = None
    ) -> Meeting:
        """Load a meeting or raise a consistent not-found error."""
        statement = select(Meeting).where(Meeting.id == meeting_id)
        if owner_id is not None:
            statement = statement.where(Meeting.owner_id == owner_id)
        result = await db.execute(statement)
        meeting = result.scalar_one_or_none()
        if meeting is None:
            raise NotFoundError("Meeting", meeting_id)
        return meeting

    async def start_stream(
        self, db: AsyncSession, meeting_id: str, session_id: str, owner_id: str | None = None
    ) -> Meeting:
        """Claim one stream and authoritatively transition created to active."""
        meeting = await self.get_meeting(db, meeting_id, owner_id)
        async with self._session_lock:
            if meeting_id in self._closing_meetings:
                raise MeetingProtocolError(
                    "Meeting audio session is closing; retry shortly.",
                    "ACTIVE_AUDIO_SESSION",
                )
            existing_session = self._sessions.get(meeting_id)
            if existing_session is not None and existing_session != session_id:
                raise MeetingProtocolError(
                    "Another audio stream is already active for this meeting.",
                    "ACTIVE_AUDIO_SESSION",
                )
            if meeting.status == MeetingStatus.STOPPED.value:
                raise MeetingProtocolError(
                    "Stopped meetings cannot be started.", "MEETING_NOT_STARTABLE"
                )
            if meeting.status == MeetingStatus.FAILED.value:
                raise MeetingProtocolError(
                    "Failed meetings cannot be started.", "MEETING_NOT_STARTABLE"
                )

            engine = await self._ensure_transcription_engine()
            consumer = self._make_consumer(
                meeting_id,
                engine,
                self._session_factory_for(db),
            )
            self._ensure_answer_worker(meeting_id, session_id, meeting.owner_id)
            try:
                await self.processor.start(
                    meeting_id,
                    session_id,
                    consumer=consumer,
                    window_ms=settings.meeting_pcm_window_ms,
                )
            except Exception:
                await self._close_answer_worker(meeting_id, session_id, drain=False)
                raise
            self._sessions[meeting_id] = session_id
            self._event_queues.setdefault(meeting_id, asyncio.Queue(maxsize=128))
            if meeting.status == MeetingStatus.CREATED.value:
                meeting.status = MeetingStatus.ACTIVE.value
                meeting.started_at = datetime.now(UTC)
                await db.commit()
                await db.refresh(meeting)
            return meeting

    async def claim_stream(
        self, db: AsyncSession, meeting_id: str, session_id: str, owner_id: str | None = None
    ) -> Meeting:
        """Reserve the sole WebSocket session without starting the meeting."""
        meeting = await self.get_meeting(db, meeting_id, owner_id)
        async with self._session_lock:
            if meeting_id in self._closing_meetings:
                raise MeetingProtocolError(
                    "Meeting audio session is closing; retry shortly.",
                    "ACTIVE_AUDIO_SESSION",
                )
            existing_session = self._sessions.get(meeting_id)
            if existing_session is not None and existing_session != session_id:
                raise MeetingProtocolError(
                    "Another audio stream is already active for this meeting.",
                    "ACTIVE_AUDIO_SESSION",
                )
            if meeting.status in {MeetingStatus.STOPPED.value, MeetingStatus.FAILED.value}:
                raise MeetingProtocolError(
                    "Meeting is no longer streamable.", "MEETING_NOT_STREAMABLE"
                )
            self._sessions[meeting_id] = session_id
            self._event_queues.setdefault(meeting_id, asyncio.Queue(maxsize=128))
            return meeting

    def event_queue(self, meeting_id: str, session_id: str) -> asyncio.Queue[dict[str, object]]:
        """Return the bounded event queue for the active stream session."""
        if self._sessions.get(meeting_id) != session_id:
            raise MeetingProtocolError("Audio session is not active.", "AUDIO_SESSION_NOT_ACTIVE")
        return self._event_queues.setdefault(meeting_id, asyncio.Queue(maxsize=128))

    async def accept_audio(
        self,
        db: AsyncSession,
        meeting_id: str,
        session_id: str,
        header: AudioEnvelopeHeader,
        payload: bytes,
        owner_id: str | None = None,
    ) -> bool:
        """Validate lifecycle/session state and accept through the processor."""
        meeting = await self.get_meeting(db, meeting_id, owner_id)
        if not meeting.consent_policy_version or meeting.consent_attested_at is None:
            raise ConsentRequiredError()
        if meeting.status != MeetingStatus.ACTIVE.value:
            raise MeetingProtocolError("Audio is accepted only after start.", "MEETING_NOT_ACTIVE")
        if self._sessions.get(meeting_id) != session_id:
            raise MeetingProtocolError("Audio session is not active.", "AUDIO_SESSION_NOT_ACTIVE")
        return await self.processor.accept(meeting_id, session_id, header, payload)

    async def source_ended(
        self,
        meeting_id: str,
        session_id: str,
        source: AudioSource,
    ) -> None:
        """End one source without stopping the other source or meeting."""
        await self.processor.source_ended(meeting_id, session_id, source)

    async def disconnect_stream(self, meeting_id: str, session_id: str) -> None:
        """Release a disconnected stream while leaving the meeting active."""
        async with self._session_lock:
            if self._sessions.get(meeting_id) != session_id:
                return
            closing = asyncio.Event()
            self._closing_meetings[meeting_id] = closing
            self._sessions.pop(meeting_id, None)
            self._event_queues.pop(meeting_id, None)
        try:
            await self.processor.abort(meeting_id, session_id)
            await self.processor.purge(meeting_id, session_id)
        finally:
            await self._close_answer_worker(meeting_id, session_id, drain=False)
            async with self._session_lock:
                self._closing_meetings.pop(meeting_id, None)
                closing.set()

    async def stop_meeting(
        self, db: AsyncSession, meeting_id: str, owner_id: str | None = None
    ) -> Meeting:
        """Stop a meeting idempotently and clean up its active processor."""
        meeting = await self.get_meeting(db, meeting_id, owner_id)
        async with self._session_lock:
            closing = self._closing_meetings.get(meeting_id)
            if closing is None:
                session_id = self._sessions.pop(meeting_id, None)
                if session_id is not None:
                    closing = asyncio.Event()
                    self._closing_meetings[meeting_id] = closing
            else:
                session_id = None
        if closing is not None and session_id is None:
            await closing.wait()
            await db.refresh(meeting)
            if meeting.status in {MeetingStatus.STOPPED.value, MeetingStatus.FAILED.value}:
                return meeting
        if meeting.status not in {MeetingStatus.STOPPED.value, MeetingStatus.FAILED.value}:
            meeting.status = MeetingStatus.STOPPED.value
            meeting.stopped_at = datetime.now(UTC)
            await db.commit()
            await db.refresh(meeting)
        try:
            if session_id is not None:
                await self.processor.stop(meeting_id, session_id)
                await self.processor.purge(meeting_id, session_id)
        finally:
            if session_id is not None:
                await self._close_answer_worker(meeting_id, session_id, drain=True)
            self._event_queues.pop(meeting_id, None)
            if closing is not None:
                async with self._session_lock:
                    self._closing_meetings.pop(meeting_id, None)
                    closing.set()
        return meeting

    async def fail_meeting(
        self,
        db: AsyncSession,
        meeting_id: str,
        reason: str,
        session_id: str | None = None,
        owner_id: str | None = None,
    ) -> Meeting:
        """Transition to failed and purge any associated processor state."""
        meeting = await self.get_meeting(db, meeting_id, owner_id)
        active_session = self._sessions.get(meeting_id)
        if active_session is not None and (session_id is None or session_id == active_session):
            try:
                await self.processor.fail(meeting_id, active_session, reason)
                await self.processor.purge(meeting_id, active_session)
            finally:
                self._sessions.pop(meeting_id, None)
                self._event_queues.pop(meeting_id, None)
                await self._close_answer_worker(meeting_id, active_session, drain=False)
        if meeting.status == MeetingStatus.STOPPED.value:
            return meeting
        if meeting.status != MeetingStatus.FAILED.value:
            meeting.status = MeetingStatus.FAILED.value
            meeting.failed_at = datetime.now(UTC)
            meeting.failure_reason = reason[:500]
            await db.commit()
            await db.refresh(meeting)
        return meeting

    async def reconcile_active_meetings(self, db: AsyncSession | None = None) -> int:
        """Close meetings left active when a previous backend process stopped.

        Audio sessions are process-local, so an ``active`` meeting found during
        startup cannot be resumed or have its missing audio reconstructed.  The
        meeting is therefore marked failed while its persisted transcript and
        other child records remain untouched.

        Args:
            db: Optional application database session.  When omitted, a short-lived
                session is created from the application database factory.

        Returns:
            The number of stale active meetings transitioned to ``failed``.
        """
        if db is None:
            factory = self.session_factory
            if factory is None:
                from app.services.database import get_app_session_factory

                factory = get_app_session_factory()
            async with factory() as reconciliation_db:
                return await self._reconcile_active_meetings(reconciliation_db)
        return await self._reconcile_active_meetings(db)

    async def _reconcile_active_meetings(self, db: AsyncSession) -> int:
        """Apply the startup terminal transition in one database transaction."""
        result = await db.execute(
            select(Meeting).where(Meeting.status == MeetingStatus.ACTIVE.value)
        )
        meetings = list(result.scalars().all())
        if not meetings:
            return 0

        failed_at = datetime.now(UTC)
        for meeting in meetings:
            meeting.status = MeetingStatus.FAILED.value
            meeting.failed_at = failed_at
            meeting.failure_reason = INTERRUPTED_MEETING_REASON
        await db.commit()
        logger.warning("meetings_reconciled_after_restart", count=len(meetings))
        return len(meetings)

    async def delete_meeting(
        self, db: AsyncSession, meeting_id: str, owner_id: str | None = None
    ) -> None:
        """Delete a meeting and all children after purging audio state."""
        await self.get_meeting(db, meeting_id, owner_id)
        session_id = self._sessions.pop(meeting_id, None)
        try:
            await self.processor.purge(meeting_id, session_id)
        finally:
            await self._close_answer_worker(meeting_id, session_id, drain=False)
            self._event_queues.pop(meeting_id, None)
        await db.execute(delete(DetectedQuestion).where(DetectedQuestion.meeting_id == meeting_id))
        await db.execute(
            delete(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
        )
        statement = delete(Meeting).where(Meeting.id == meeting_id)
        if owner_id is not None:
            statement = statement.where(Meeting.owner_id == owner_id)
        await db.execute(statement)
        await db.commit()
        logger.info("meeting_deleted", meeting_id=meeting_id)

    async def _ensure_transcription_engine(self) -> TranscriptionEngine:
        """Preflight and load ASR before authoritative meeting activation."""
        if self.transcription_engine is None:
            try:
                self.transcription_engine = get_local_asr_engine()
            except Exception as exc:
                raise MeetingProtocolError(
                    f"Local ASR is not ready: {exc}",
                    "ASR_NOT_READY",
                ) from exc
        if self._asr_ready:
            return self.transcription_engine
        load_task = self._asr_load_task
        if load_task is None:
            load_task = asyncio.create_task(self._load_transcription_engine())
            self._asr_load_task = load_task
        try:
            await asyncio.wait_for(asyncio.shield(load_task), timeout=ASR_READINESS_TIMEOUT_SECONDS)
        except asyncio.TimeoutError as exc:
            raise MeetingProtocolError(
                "Local ASR is not ready: readiness check timed out; try again shortly.",
                "ASR_NOT_READY",
            ) from exc
        except Exception as exc:
            if self._asr_load_task is load_task:
                self._asr_load_task = None
            raise MeetingProtocolError(
                f"Local ASR is not ready: {exc}",
                "ASR_NOT_READY",
            ) from exc
        self._asr_ready = True
        if self._asr_load_task is load_task:
            self._asr_load_task = None
        return self.transcription_engine

    async def _load_transcription_engine(self) -> None:
        """Load the required ASR engine once for this service process."""
        load = getattr(self.transcription_engine, "load", None)
        if load is not None:
            await load()

    def _make_consumer(
        self,
        meeting_id: str,
        engine: TranscriptionEngine,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> WindowConsumer:
        """Build the asynchronous transcription/persistence callback."""

        async def consume(
            header: AudioEnvelopeHeader, payload: bytes, offset_ms: int, final: bool
        ) -> None:
            try:
                chunks = await engine.transcribe(
                    payload,
                    sample_rate_hz=header.sample_rate_hz,
                    channels=header.channels,
                    source=header.source,
                    final=final,
                )
            except Exception as exc:
                await self._emit(
                    meeting_id,
                    MeetingDegradedEvent(
                        meeting_id=meeting_id,
                        component="asr",
                        message="Local transcription is unavailable; capture continues.",
                    ),
                )
                logger.warning("meeting_asr_degraded", meeting_id=meeting_id, error=str(exc))
                return

            for chunk in chunks:
                text = chunk.text.strip()
                if not text:
                    continue
                async with session_factory() as inference_db, inference_db.begin():
                    sequence = await self._allocate_transcript_sequence(inference_db, meeting_id)
                    segment = TranscriptSegment(
                        meeting_id=meeting_id,
                        sequence=sequence,
                        source=header.source.value,
                        speaker=header.source.value,
                        text=text,
                        start_ms=offset_ms + chunk.start_ms,
                        end_ms=offset_ms + chunk.end_ms,
                    )
                    inference_db.add(segment)
                    await inference_db.flush()

                    question = self.question_detector.detect(text, header.source)
                    detected = None
                    if question is not None:
                        detected = DetectedQuestion(
                            meeting_id=meeting_id,
                            transcript_segment_id=segment.id,
                            question=question,
                        )
                        inference_db.add(detected)
                        await inference_db.flush()

                await self._emit(
                    meeting_id,
                    MeetingTranscriptEvent(
                        meeting_id=meeting_id,
                        segment_id=segment.id,
                        source=header.source,
                        text=text,
                        start_ms=offset_ms + chunk.start_ms,
                        end_ms=offset_ms + chunk.end_ms,
                    ),
                )

                if detected is None:
                    continue
                await self._emit(
                    meeting_id,
                    MeetingQuestionEvent(
                        meeting_id=meeting_id,
                        question_id=detected.id,
                        text=detected.question,
                    ),
                )
                await self._enqueue_answer(
                    meeting_id,
                    PendingMeetingAnswer(
                        question_id=detected.id,
                        question=detected.question,
                    ),
                )

        return consume

    def _ensure_answer_worker(
        self,
        meeting_id: str,
        session_id: str,
        owner_id: str,
    ) -> asyncio.Queue[PendingMeetingAnswer]:
        """Create one bounded answer worker for the claimed stream session."""
        worker = self._answer_workers.get(meeting_id)
        if (
            worker is not None
            and not worker.done()
            and self._answer_sessions.get(meeting_id) == session_id
        ):
            return self._answer_queues[meeting_id]

        queue: asyncio.Queue[PendingMeetingAnswer] = asyncio.Queue(maxsize=ANSWER_QUEUE_SIZE)
        self._answer_queues[meeting_id] = queue
        self._answer_sessions[meeting_id] = session_id
        self._answer_workers[meeting_id] = asyncio.create_task(
            self._run_answer_worker(meeting_id, session_id, owner_id, queue)
        )
        return queue

    async def _enqueue_answer(self, meeting_id: str, request: PendingMeetingAnswer) -> None:
        """Queue an answer request without delaying serialized transcription."""
        queue = self._answer_queues.get(meeting_id)
        if queue is None:
            return
        try:
            queue.put_nowait(request)
        except asyncio.QueueFull:
            await self._emit(
                meeting_id,
                MeetingDegradedEvent(
                    meeting_id=meeting_id,
                    component="ollama",
                    message="Private answer queue is full; transcription continues. Try again later.",
                ),
            )

    async def _run_answer_worker(
        self,
        meeting_id: str,
        session_id: str,
        owner_id: str,
        queue: asyncio.Queue[PendingMeetingAnswer],
    ) -> None:
        """Process answer work independently from the audio processor worker."""
        timeout = float(
            getattr(
                self.answer_service, "provider_timeout_seconds", ANSWER_PROVIDER_TIMEOUT_SECONDS
            )
        )
        request_timeout = timeout * 2 + ANSWER_DRAIN_GRACE_SECONDS
        try:
            while True:
                request = await queue.get()
                try:
                    if self._answer_sessions.get(meeting_id) != session_id:
                        continue
                    try:
                        suggestion = await asyncio.wait_for(
                            self.answer_service.suggest(request.question, owner_id=owner_id),
                            timeout=request_timeout,
                        )
                    except asyncio.TimeoutError:
                        await self._emit(
                            meeting_id,
                            MeetingDegradedEvent(
                                meeting_id=meeting_id,
                                component="ollama",
                                message="Private answer suggestions timed out; transcription continues.",
                            ),
                        )
                        continue
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        await self._emit(
                            meeting_id,
                            MeetingDegradedEvent(
                                meeting_id=meeting_id,
                                component="ollama",
                                message="Private answer suggestions are unavailable.",
                            ),
                        )
                        logger.warning(
                            "meeting_ollama_degraded", meeting_id=meeting_id, error=str(exc)
                        )
                        continue

                    if self._answer_sessions.get(meeting_id) != session_id:
                        continue
                    for component in suggestion.degraded_components:
                        await self._emit(
                            meeting_id,
                            MeetingDegradedEvent(
                                meeting_id=meeting_id,
                                component=component,
                                message=f"{component.upper()} context is unavailable; answer used remaining local context.",
                            ),
                        )
                    await self._emit(
                        meeting_id,
                        MeetingAnswerEvent(
                            meeting_id=meeting_id,
                            question_id=request.question_id,
                            answer=suggestion.answer,
                            citations=suggestion.citations,
                        ),
                    )
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            raise

    async def _close_answer_worker(
        self,
        meeting_id: str,
        session_id: str | None,
        *,
        drain: bool,
    ) -> None:
        """Drain or cancel a session's answer worker and discard its queue."""
        answer_session = self._answer_sessions.get(meeting_id)
        if answer_session is None or (session_id is not None and answer_session != session_id):
            return
        queue = self._answer_queues.get(meeting_id)
        worker = self._answer_workers.get(meeting_id)
        if drain and queue is not None and worker is not None:
            timeout = float(
                getattr(
                    self.answer_service, "provider_timeout_seconds", ANSWER_PROVIDER_TIMEOUT_SECONDS
                )
            )
            try:
                await asyncio.wait_for(
                    queue.join(), timeout=timeout * 2 + ANSWER_DRAIN_GRACE_SECONDS
                )
            except asyncio.TimeoutError:
                logger.warning("meeting_answer_drain_timeout", meeting_id=meeting_id)
        if worker is not None and not worker.done():
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        self._answer_queues.pop(meeting_id, None)
        self._answer_workers.pop(meeting_id, None)
        self._answer_sessions.pop(meeting_id, None)

    def _session_factory_for(self, db: AsyncSession) -> async_sessionmaker[AsyncSession]:
        """Return a factory for isolated background sessions on the app database."""
        if self.session_factory is not None:
            return self.session_factory
        if db.bind is None:
            raise RuntimeError("Meeting database session has no bind")
        return async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)

    @staticmethod
    async def _allocate_transcript_sequence(db: AsyncSession, meeting_id: str) -> int:
        """Atomically reserve the next persisted transcript sequence."""
        from sqlalchemy import update

        result = await db.execute(
            update(Meeting)
            .where(Meeting.id == meeting_id)
            .values(next_transcript_sequence=Meeting.next_transcript_sequence + 1)
            .returning(Meeting.next_transcript_sequence)
        )
        next_sequence = result.scalar_one_or_none()
        if next_sequence is None:
            raise NotFoundError("Meeting", meeting_id)
        return int(next_sequence) - 1

    async def _emit(self, meeting_id: str, event: BaseModel) -> None:
        """Enqueue a typed event without blocking audio acceptance."""
        queue = self._event_queues.get(meeting_id)
        if queue is None:
            return
        payload = event.model_dump(mode="json")
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning("meeting_event_backpressure", meeting_id=meeting_id)

    # Concise lifecycle names for service callers.
    create = create_meeting
    start = start_stream
    start_meeting = start_stream
    accept_audio_chunk = accept_audio
    stop = stop_meeting
    delete = delete_meeting
    reconcile_interrupted_meetings = reconcile_active_meetings


meeting_service = MeetingService()

__all__ = ["INTERRUPTED_MEETING_REASON", "MeetingService", "meeting_service"]
