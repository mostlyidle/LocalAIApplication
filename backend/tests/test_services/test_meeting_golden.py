"""Golden compatibility test for the desktop meeting-audio.v1 envelope."""

from __future__ import annotations

from app.models.enums import AudioSource
from app.models.schemas import decode_audio_envelope


def test_desktop_golden_envelope_decodes_without_duration_rounding(golden_envelope: bytes) -> None:
    """The backend must consume the shared header and exact frame_count bytes."""
    header, payload = decode_audio_envelope(golden_envelope, "meeting-123")

    assert header.protocol == "meeting-audio.v1"
    assert header.source == AudioSource.MICROPHONE
    assert header.meeting_id == "meeting-123"
    assert header.sequence == 7
    assert header.timestamp_ns == 123_456_789
    assert header.sample_rate_hz == 48_000
    assert header.channels == 1
    assert header.encoding == "pcm_s16le"
    assert header.frame_count == 4
    assert header.duration_ms == 0
    assert payload == bytes((0x00, 0x00, 0xFF, 0x3F, 0x00, 0x80, 0xFF, 0x7F))
