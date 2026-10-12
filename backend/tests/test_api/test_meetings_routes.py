"""Tests for the hardened meeting lifecycle API."""

from __future__ import annotations

import hashlib
import json
import struct
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from app.api.routes.meetings import _is_allowed_origin
from app.dependencies import get_meeting_service
from app.models.db_models import Meeting, MeetingStreamTicket
from app.models.enums import MeetingStatus
from app.services.meeting_answers import MeetingAnswerService
from app.services.meetings import MeetingService
from app.services.transcription import FakeTranscriptionEngine, TranscriptionChunk

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


def _consent() -> dict[str, str]:
    """Return the canonical consent receipt payload."""
    return {
        "consent_policy_version": "meeting-consent-v1",
        "consent_attested_at": datetime.now(UTC).isoformat(),
    }


class TestMeetingRoutes:
    def test_websocket_origin_allowlist(self):
        assert _is_allowed_origin("http://localhost:3000")
        assert _is_allowed_origin("tauri://localhost")
        assert not _is_allowed_origin("https://attacker.example")
        assert not _is_allowed_origin(None)

    async def test_create_rejects_legacy_or_extra_consent_fields(self, client: AsyncClient):
        response = await client.post("/api/v1/meetings", json={"consent": True})

        assert response.status_code == 422

    async def test_lifecycle_and_idempotent_stop(self, client: AsyncClient):
        response = await client.post("/api/v1/meetings", json=_consent())
        assert response.status_code == 200
        data = response.json()
        meeting_id = data["id"]
        assert data["status"] == "created"
        assert data["started_at"] is None
        assert data["consent_policy_version"] == "meeting-consent-v1"

        fetched = await client.get(f"/api/v1/meetings/{meeting_id}")
        assert fetched.status_code == 200
        assert fetched.json()["status"] == "created"

        stopped = await client.post(f"/api/v1/meetings/{meeting_id}/stop")
        stopped_again = await client.post(f"/api/v1/meetings/{meeting_id}/stop")
        assert stopped.status_code == 200
        assert stopped_again.status_code == 200
        assert stopped.json()["stopped_at"] == stopped_again.json()["stopped_at"]

        deleted = await client.delete(f"/api/v1/meetings/{meeting_id}")
        assert deleted.status_code == 200
        assert (await client.get(f"/api/v1/meetings/{meeting_id}")).status_code == 404

    async def test_native_stream_ticket_is_stored_as_a_hash(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        meeting_response = await client.post("/api/v1/meetings", json=_consent())
        meeting_id = meeting_response.json()["id"]

        response = await client.post(f"/api/v1/meetings/{meeting_id}/stream-ticket")

        assert response.status_code == 200
        raw_ticket = response.json()["ticket"]
        stored = await db_session.get(
            MeetingStreamTicket, hashlib.sha256(raw_ticket.encode("utf-8")).hexdigest()
        )
        assert stored is not None
        assert stored.meeting_id == meeting_id


def _frame_with_sequence(
    envelope: bytes,
    sequence: int,
    timestamp_ns: int,
    source: str | None = None,
) -> bytes:
    """Adjust only sequencing metadata while retaining the shared wire format."""
    header_length = int.from_bytes(envelope[:4], "big")
    header_start = 4
    header_end = header_start + header_length
    header = json.loads(envelope[header_start:header_end].decode("utf-8"))
    header["sequence"] = sequence
    header["timestamp_ns"] = timestamp_ns
    if source is not None:
        header["source"] = source
    encoded_header = json.dumps(header, separators=(",", ":")).encode("utf-8")
    return struct.pack(">I", len(encoded_header)) + encoded_header + envelope[header_end:]


async def test_canonical_meeting_stream_protocol(
    app,
    client: AsyncClient,
    db_session: AsyncSession,
    golden_envelope: bytes,
):
    """Exercise origin, start, binary ACK/retry, source end, and cleanup."""
    meeting_id = "meeting-123"
    db_session.add(
        Meeting(
            id=meeting_id,
            status=MeetingStatus.CREATED.value,
            consent_policy_version="meeting-consent-v1",
            consent_attested_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    class FailingAnswerGenerator:
        async def generate(self, question: str, context: str) -> str:
            raise RuntimeError("Ollama is unavailable")

    fake_service = MeetingService(
        transcription_engine=FakeTranscriptionEngine([TranscriptionChunk("What is next?")]),
        answer_service=MeetingAnswerService(generator=FailingAnswerGenerator()),
    )
    app.dependency_overrides[get_meeting_service] = lambda: fake_service
    ws_client = TestClient(app)
    try:
        with ws_client.websocket_connect(
            f"/api/v1/meetings/{meeting_id}/stream",
            headers={"origin": "https://attacker.example"},
        ) as websocket:
            origin_error = websocket.receive_json()
            assert origin_error == {
                "type": "error",
                "code": "ORIGIN_NOT_ALLOWED",
                "message": "WebSocket origin is not allowed.",
                "sequence": None,
            }

        with ws_client.websocket_connect(
            f"/api/v1/meetings/{meeting_id}/stream",
            headers={"origin": "http://localhost:3000"},
        ) as websocket:
            created = websocket.receive_json()
            assert created["type"] == "status"
            assert created["status"] == "created"

            websocket.send_bytes(golden_envelope)
            before_start = websocket.receive_json()
            assert before_start["type"] == "error"
            assert before_start["code"] == "AUDIO_BEFORE_START"

            websocket.send_json({"type": "start"})
            started = websocket.receive_json()
            assert started["type"] == "status"
            assert started["status"] == "active"

            # The shared golden is sequence 7. Feed the preceding frames using
            # the same envelope metadata so the real per-source sequencer can
            # reach and acknowledge the unmodified golden frame.
            for sequence in range(7):
                websocket.send_bytes(
                    _frame_with_sequence(golden_envelope, sequence, 123_456_780 + sequence)
                )
                warmup_ack = websocket.receive_json()
                assert warmup_ack["type"] == "ack"
                assert warmup_ack["sequence"] == sequence
                assert warmup_ack["duplicate"] is False

            websocket.send_bytes(golden_envelope)
            ack = websocket.receive_json()
            assert ack == {
                "type": "ack",
                "source": "microphone",
                "sequence": 7,
                "duplicate": False,
            }

            websocket.send_bytes(golden_envelope)
            duplicate_ack = websocket.receive_json()
            assert duplicate_ack["type"] == "ack"
            assert duplicate_ack["sequence"] == 7
            assert duplicate_ack["duplicate"] is True

            websocket.send_json({"type": "source_ended", "source": "microphone"})
            source_ended = websocket.receive_json()
            assert source_ended == {
                "type": "source_status",
                "meeting_id": meeting_id,
                "source": "microphone",
                "status": "ended",
            }
            microphone_transcript = websocket.receive_json()
            assert microphone_transcript["type"] == "transcript"
            assert microphone_transcript["source"] == "microphone"

            websocket.send_bytes(
                _frame_with_sequence(golden_envelope, 0, 123_456_790, source="system")
            )
            system_ack = websocket.receive_json()
            assert system_ack["source"] == "system"
            assert system_ack["sequence"] == 0
            websocket.send_json({"type": "source_ended", "source": "system"})
            system_events = [websocket.receive_json() for _ in range(5)]
            assert {event["type"] for event in system_events} == {
                "source_status",
                "transcript",
                "question",
                "degraded",
                "answer",
            }
            system_source_ended = next(
                event for event in system_events if event["type"] == "source_status"
            )
            assert system_source_ended["source"] == "system"
            transcript = next(event for event in system_events if event["type"] == "transcript")
            assert transcript["source"] == "system"
            assert next(event for event in system_events if event["type"] == "question")["text"] == "What is next?"
            assert next(event for event in system_events if event["type"] == "degraded")["component"] == "ollama"
            assert next(event for event in system_events if event["type"] == "answer")["answer"] == "No local answer is available."

            websocket.send_json({"type": "stop"})
            stopped = websocket.receive_json()
            assert stopped["type"] == "status"
            assert stopped["status"] == "stopped"
    finally:
        ws_client.close()

    assert meeting_id not in fake_service._sessions
    assert meeting_id not in fake_service.processor._sessions
    stopped_response = await client.get(f"/api/v1/meetings/{meeting_id}")
    assert stopped_response.json()["status"] == "stopped"
