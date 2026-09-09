use serde::Serialize;
use thiserror::Error;

use crate::model::{
    CaptureSource, MAX_TRANSPORT_HEADER_BYTES, MAX_TRANSPORT_PAYLOAD_BYTES, PCM_PROTOCOL,
};

const MAX_MEETING_ID_BYTES: usize = 36;

#[derive(Debug, Error, PartialEq, Eq)]
pub enum TransportError {
    #[error("meeting_id must be between 1 and 36 UTF-8 bytes")]
    InvalidMeetingId,
    #[error("sample rate and channels must be non-zero")]
    InvalidFormat,
    #[error("PCM payload exceeds the bounded transport limit")]
    PayloadTooLarge,
    #[error("transport header is too large")]
    HeaderTooLarge,
}

#[derive(Clone, Debug, Serialize)]
pub struct AudioEnvelopeHeader<'a> {
    pub protocol: &'static str,
    pub meeting_id: &'a str,
    pub source: &'static str,
    pub sequence: u64,
    pub timestamp_ns: u64,
    pub sample_rate_hz: u32,
    pub channels: u16,
    pub encoding: &'static str,
    pub frame_count: u32,
    pub duration_ms: u32,
}

/// Builds the binary frame sent by the future direct desktop-to-FastAPI WebSocket.
///
/// Wire format: `[4-byte big-endian JSON length][UTF-8 JSON header][bounded PCM]`.
/// This builder is deliberately not exposed as a Tauri command: PCM stays native.
pub fn build_audio_envelope(
    meeting_id: &str,
    source: CaptureSource,
    sequence: u64,
    timestamp_ns: u64,
    sample_rate_hz: u32,
    channels: u16,
    pcm_f32: &[f32],
) -> Result<Vec<u8>, TransportError> {
    if meeting_id.is_empty() || meeting_id.len() > MAX_MEETING_ID_BYTES {
        return Err(TransportError::InvalidMeetingId);
    }
    if timestamp_ns == 0
        || !(8_000..=96_000).contains(&sample_rate_hz)
        || !(1..=2).contains(&channels)
    {
        return Err(TransportError::InvalidFormat);
    }
    if pcm_f32.is_empty() || pcm_f32.len() % usize::from(channels) != 0 {
        return Err(TransportError::InvalidFormat);
    }
    let frame_count_usize = pcm_f32.len() / usize::from(channels);
    if frame_count_usize > sample_rate_hz as usize {
        return Err(TransportError::PayloadTooLarge);
    }
    let frame_count =
        u32::try_from(frame_count_usize).map_err(|_| TransportError::PayloadTooLarge)?;
    let pcm_bytes = pcm_f32
        .len()
        .checked_mul(2)
        .ok_or(TransportError::PayloadTooLarge)?;
    if pcm_bytes > MAX_TRANSPORT_PAYLOAD_BYTES {
        return Err(TransportError::PayloadTooLarge);
    }
    // Informational only. Payload validation uses frame_count, never this lossy integer value.
    let duration_ms = (u64::from(frame_count) * 1_000 / u64::from(sample_rate_hz)) as u32;
    let header = AudioEnvelopeHeader {
        protocol: PCM_PROTOCOL,
        meeting_id,
        source: source.as_str(),
        sequence,
        timestamp_ns,
        sample_rate_hz,
        channels,
        encoding: "pcm_s16le",
        frame_count,
        duration_ms,
    };
    let header = serde_json::to_vec(&header).map_err(|_| TransportError::HeaderTooLarge)?;
    if header.len() > MAX_TRANSPORT_HEADER_BYTES || header.len() > u32::MAX as usize {
        return Err(TransportError::HeaderTooLarge);
    }
    let mut envelope = Vec::with_capacity(4 + header.len() + pcm_bytes);
    envelope.extend_from_slice(&(header.len() as u32).to_be_bytes());
    envelope.extend_from_slice(&header);
    for sample in pcm_f32 {
        let sample = if sample.is_finite() {
            sample.clamp(-1.0, 1.0)
        } else {
            0.0
        };
        let value = if sample < 0.0 {
            (sample * 32_768.0) as i16
        } else {
            (sample * 32_767.0) as i16
        };
        envelope.extend_from_slice(&value.to_le_bytes());
    }
    Ok(envelope)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn envelope_has_big_endian_header_length_and_little_endian_pcm() {
        let envelope = build_audio_envelope(
            "meeting-1",
            CaptureSource::Microphone,
            7,
            99,
            48_000,
            1,
            &[0.5, -1.0],
        )
        .unwrap();
        let header_len = u32::from_be_bytes(envelope[..4].try_into().unwrap()) as usize;
        let header: serde_json::Value =
            serde_json::from_slice(&envelope[4..4 + header_len]).unwrap();
        assert_eq!(header["protocol"], PCM_PROTOCOL);
        assert_eq!(header["source"], "microphone");
        assert_eq!(header["frame_count"], 2);
        assert_eq!(&envelope[4 + header_len..], &[0xff, 0x3f, 0x00, 0x80]);
    }

    #[test]
    fn golden_envelope_matches_canonical_wire_bytes() {
        let actual = build_audio_envelope(
            "meeting-123",
            CaptureSource::Microphone,
            7,
            123_456_789,
            48_000,
            1,
            &[0.0, 0.5, -1.0, 1.0],
        )
        .unwrap();
        let expected = decode_hex(include_str!(
            "../../../meeting-contract/golden_envelope.hex"
        ));
        assert_eq!(actual, expected);
    }

    #[test]
    fn frame_count_not_rounded_duration_controls_payload() {
        let envelope =
            build_audio_envelope("id", CaptureSource::System, 0, 1, 48_000, 1, &[0.0]).unwrap();
        let header_len = u32::from_be_bytes(envelope[..4].try_into().unwrap()) as usize;
        let header: serde_json::Value =
            serde_json::from_slice(&envelope[4..4 + header_len]).unwrap();
        assert_eq!(header["frame_count"], 1);
        assert_eq!(header["duration_ms"], 0);
        assert_eq!(envelope.len() - 4 - header_len, 2);
    }

    #[test]
    fn envelope_rejects_unbounded_payload_and_bad_channel_alignment() {
        assert_eq!(
            build_audio_envelope("id", CaptureSource::System, 0, 0, 48_000, 2, &[0.0]).unwrap_err(),
            TransportError::InvalidFormat
        );
        let samples = vec![0.0; MAX_TRANSPORT_PAYLOAD_BYTES / 2 + 2];
        assert_eq!(
            build_audio_envelope("id", CaptureSource::System, 0, 1, 96_000, 2, &samples)
                .unwrap_err(),
            TransportError::PayloadTooLarge
        );
    }

    fn decode_hex(value: &str) -> Vec<u8> {
        value
            .split_whitespace()
            .map(|byte| u8::from_str_radix(byte, 16).unwrap())
            .collect()
    }
}
