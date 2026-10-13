"""Consent-gated meeting lifecycle and canonical binary audio WebSocket."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import secrets
import time
import uuid
from urllib.parse import urlparse

import structlog
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,  # noqa: TC002 - FastAPI resolves this annotation at runtime
)

from app.api.middleware.error_handler import AppError
from app.config import settings
from app.dependencies import (
    WEBSOCKET_SESSION_RECHECK_SECONDS,
    get_authenticated_session,
    get_db,
    get_meeting_service,
    get_websocket_session,
    websocket_session_is_active,
)
from app.models.db_models import DetectedQuestion, Meeting, MeetingStreamTicket, TranscriptSegment
from app.models.enums import MeetingStatus
from app.models.schemas import (
    AudioEnvelopeError,
    MeetingAudioAck,
    MeetingClientMessage,
    MeetingCreateRequest,
    MeetingDeleteResponse,
    MeetingErrorEvent,
    MeetingResponse,
    MeetingSourceEnded,
    MeetingSourceListItem,
    MeetingSourceStatusEvent,
    MeetingStatusEvent,
    MeetingStopCommand,
    MeetingStopResponse,
    MeetingStreamTicketResponse,
    decode_audio_envelope,
)
from app.services.auth import (
    AuthenticatedSession,  # noqa: TC001 - FastAPI resolves this annotation at runtime
)
from app.services.meetings import (
    MeetingService,  # noqa: TC001 - FastAPI resolves this annotation at runtime
)

logger = structlog.get_logger(__name__)
router = APIRouter()
_client_message_adapter = TypeAdapter(MeetingClientMessage)


@router.get("/meetings", response_model=list[MeetingSourceListItem])
async def list_meetings(
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> list[MeetingSourceListItem]:
    """List meeting metadata belonging to the signed-in account."""
    rows = await db.scalars(
        select(Meeting)
        .where(Meeting.owner_id == authenticated.account.id)
        .order_by(Meeting.created_at.desc())
        .limit(100)
    )
    return [MeetingSourceListItem.model_validate(row, from_attributes=True) for row in rows.all()]


@router.post("/meetings", response_model=MeetingResponse)
async def create_meeting(
    body: MeetingCreateRequest,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    service: MeetingService = Depends(get_meeting_service),  # noqa: B008
) -> MeetingResponse:
    """Create a meeting with one canonical consent receipt."""
    meeting = await service.create_meeting(
        db,
        owner_id=authenticated.account.id,
        consent_policy_version=body.consent_policy_version,
        consent_attested_at=body.consent_attested_at,
    )
    return await _meeting_response(db, meeting)


@router.get("/meetings/{meeting_id}", response_model=MeetingResponse)
async def get_meeting(
    meeting_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    service: MeetingService = Depends(get_meeting_service),  # noqa: B008
) -> MeetingResponse:
    """Return meeting metadata without audio payloads."""
    meeting = await service.get_meeting(db, meeting_id, authenticated.account.id)
    return await _meeting_response(db, meeting)


@router.post("/meetings/{meeting_id}/stream-ticket", response_model=MeetingStreamTicketResponse)
async def create_meeting_stream_ticket(
    meeting_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    service: MeetingService = Depends(get_meeting_service),  # noqa: B008
) -> MeetingStreamTicketResponse:
    """Issue a session-bound bearer ticket for the native meeting WebSocket."""
    await service.get_meeting(db, meeting_id, authenticated.account.id)
    ticket = secrets.token_urlsafe(32)
    db.add(
        MeetingStreamTicket(
            token_hash=hashlib.sha256(ticket.encode("utf-8")).hexdigest(),
            meeting_id=meeting_id,
            session_id=authenticated.session.id,
            expires_at=authenticated.session.expires_at,
        )
    )
    await db.commit()
    return MeetingStreamTicketResponse(ticket=ticket)


@router.post("/meetings/{meeting_id}/stop", response_model=MeetingStopResponse)
async def stop_meeting(
    meeting_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    service: MeetingService = Depends(get_meeting_service),  # noqa: B008
) -> MeetingStopResponse:
    """Stop a meeting and clean up its processor session idempotently."""
    meeting = await service.stop_meeting(db, meeting_id, authenticated.account.id)
    response = await _meeting_response(db, meeting)
    return MeetingStopResponse(**response.model_dump())


@router.delete("/meetings/{meeting_id}", response_model=MeetingDeleteResponse)
async def delete_meeting(
    meeting_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    service: MeetingService = Depends(get_meeting_service),  # noqa: B008
) -> MeetingDeleteResponse:
    """Delete a meeting and purge all processor/child state."""
    await service.delete_meeting(db, meeting_id, authenticated.account.id)
    return MeetingDeleteResponse(meeting_id=meeting_id)


@router.websocket("/meetings/{meeting_id}/stream")
async def meeting_stream(
    websocket: WebSocket,
    meeting_id: str,
    authenticated: AuthenticatedSession = Depends(get_websocket_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
    service: MeetingService = Depends(get_meeting_service),  # noqa: B008
) -> None:
    """Accept strict JSON controls and bounded binary PCM envelopes.

    Canonical wire format for a binary message:
    ``4-byte big-endian header length + UTF-8 JSON header + PCM``.  The
    processor acknowledgement is sent only after the processor accepts the
    frame, and no raw bytes are persisted.
    """
    await websocket.accept()
    if not _is_allowed_origin(websocket.headers.get("origin")):
        await _send_error(websocket, "ORIGIN_NOT_ALLOWED", "WebSocket origin is not allowed.")
        await websocket.close(code=4403)
        return

    session_id = str(uuid.uuid4())
    event_task: asyncio.Task[None] | None = None
    last_session_check = time.monotonic()

    async def check_session() -> bool:
        nonlocal last_session_check
        if time.monotonic() - last_session_check < WEBSOCKET_SESSION_RECHECK_SECONDS:
            return True
        if await websocket_session_is_active(websocket, authenticated.session.id):
            last_session_check = time.monotonic()
            return True
        await service.stop_meeting(db, meeting_id, authenticated.account.id)
        await websocket.close(code=4401, reason="Session expired or revoked.")
        return False

    try:
        meeting = await service.claim_stream(db, meeting_id, session_id, authenticated.account.id)
        event_queue = service.event_queue(meeting_id, session_id)
        event_task = asyncio.create_task(_forward_events(websocket, event_queue))
        await _send_status(websocket, meeting)

        while True:
            try:
                frame = await asyncio.wait_for(
                    websocket.receive(), timeout=WEBSOCKET_SESSION_RECHECK_SECONDS
                )
            except TimeoutError:
                if not await check_session():
                    return
                continue

            if not await check_session():
                return
            if frame.get("type") == "websocket.disconnect":
                return

            binary = frame.get("bytes")
            if binary is not None:
                if meeting.status != MeetingStatus.ACTIVE.value:
                    await _send_error(
                        websocket,
                        "AUDIO_BEFORE_START",
                        "Audio is accepted only after the authoritative start command.",
                    )
                    continue
                try:
                    header, payload = decode_audio_envelope(
                        binary,
                        meeting_id,
                        now_ns=time.time_ns(),
                    )
                    duplicate = await service.accept_audio(
                        db,
                        meeting_id,
                        session_id,
                        header,
                        payload,
                        authenticated.account.id,
                    )
                except AudioEnvelopeError as exc:
                    await _send_error(websocket, exc.code, str(exc))
                    continue
                except AppError as exc:
                    await _send_error(websocket, exc.code, exc.message)
                    continue
                await _send_event(
                    websocket,
                    MeetingAudioAck(
                        source=header.source,
                        sequence=header.sequence,
                        duplicate=duplicate,
                    ),
                )
                continue

            raw_text = frame.get("text")
            if not raw_text:
                await _send_error(
                    websocket, "INVALID_MESSAGE", "Expected a JSON control message or binary audio."
                )
                continue
            try:
                payload = json.loads(raw_text)
                if not isinstance(payload, dict):
                    raise TypeError("control message must be an object")
                command = _client_message_adapter.validate_python(payload)
            except (json.JSONDecodeError, TypeError, ValidationError):
                await _send_error(
                    websocket, "INVALID_MESSAGE", "Control message does not match the protocol."
                )
                continue

            if command.type == "start":
                meeting = await service.start_stream(
                    db, meeting_id, session_id, authenticated.account.id
                )
                await _send_status(websocket, meeting)
            elif isinstance(command, MeetingSourceEnded):
                await service.source_ended(meeting_id, session_id, command.source)
                await _send_event(
                    websocket,
                    MeetingSourceStatusEvent(
                        meeting_id=meeting_id,
                        source=command.source,
                        status="ended",
                    ),
                )
            elif isinstance(command, MeetingStopCommand):
                meeting = await service.stop_meeting(db, meeting_id, authenticated.account.id)
                await event_queue.join()
                await _send_status(websocket, meeting)
                await websocket.close(code=1000)
                return
    except WebSocketDisconnect:
        logger.info("meeting_websocket_disconnected", meeting_id=meeting_id)
    except AppError as exc:
        await _send_error(websocket, exc.code, exc.message)
    except Exception as exc:
        logger.exception("meeting_stream_failed", meeting_id=meeting_id, error=str(exc))
        try:
            await service.fail_meeting(
                db, meeting_id, "Audio stream failed.", session_id, authenticated.account.id
            )
            await _send_error(websocket, "MEETING_STREAM_FAILED", "Audio stream failed.")
        except Exception:
            logger.warning("meeting_failure_persistence_failed", meeting_id=meeting_id)
    finally:
        if event_task is not None:
            event_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await event_task
        await service.disconnect_stream(meeting_id, session_id)


def _is_allowed_origin(origin: str | None) -> bool:
    """Allow configured origins plus the documented local Tauri origins."""
    if not origin:
        return False
    configured = {
        item.rstrip("/") for item in (*settings.cors_origins, *settings.meeting_allowed_origins)
    }
    tauri_origins = {
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    }
    candidate = origin.rstrip("/")
    if candidate in configured or candidate in tauri_origins:
        return True
    parsed = urlparse(candidate)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname in {"localhost", "127.0.0.1"}
        and candidate in configured
    )


async def _meeting_response(db: AsyncSession, meeting: Meeting) -> MeetingResponse:
    """Build a typed response without loading transcript text."""
    segment_count = await db.scalar(
        select(func.count(TranscriptSegment.id)).where(TranscriptSegment.meeting_id == meeting.id)
    )
    question_count = await db.scalar(
        select(func.count(DetectedQuestion.id)).where(DetectedQuestion.meeting_id == meeting.id)
    )
    return MeetingResponse(
        id=meeting.id,
        status=meeting.status,
        consent_policy_version=meeting.consent_policy_version,
        consent_attested_at=meeting.consent_attested_at,
        started_at=meeting.started_at,
        stopped_at=meeting.stopped_at,
        failed_at=meeting.failed_at,
        failure_reason=meeting.failure_reason,
        created_at=meeting.created_at,
        updated_at=meeting.updated_at,
        transcript_segment_count=int(segment_count or 0),
        detected_question_count=int(question_count or 0),
    )


async def _send_status(
    websocket: WebSocket,
    meeting: Meeting,
) -> None:
    """Send a typed lifecycle status event."""
    await _send_event(
        websocket,
        MeetingStatusEvent(type="status", status=meeting.status, meeting_id=meeting.id),
    )


async def _send_event(websocket: WebSocket, event: BaseModel) -> None:
    """Send a Pydantic event as JSON."""
    await websocket.send_json(event.model_dump(mode="json"))


async def _send_error(websocket: WebSocket, code: str, message: str) -> None:
    """Send a typed, non-sensitive protocol error."""
    await _send_event(websocket, MeetingErrorEvent(code=code, message=message))


async def _forward_events(
    websocket: WebSocket,
    event_queue: asyncio.Queue[dict[str, object]],
) -> None:
    """Forward inference events independently of binary ACK latency."""
    while True:
        event = await event_queue.get()
        try:
            await websocket.send_json(event)
        finally:
            event_queue.task_done()


__all__ = ["router"]
