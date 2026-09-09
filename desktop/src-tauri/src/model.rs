use serde::{Deserialize, Serialize};

pub const METER_EVENT: &str = "capture://meter";
pub const STATUS_EVENT: &str = "capture://status";
pub const BACKPRESSURE_EVENT: &str = "meeting://backpressure";
pub const MAX_BUFFERED_FRAMES: usize = 48_000 * 10;
pub const PCM_PROTOCOL: &str = "meeting-audio.v1";
pub const MAX_TRANSPORT_HEADER_BYTES: usize = 4_096;
pub const MAX_TRANSPORT_PAYLOAD_BYTES: usize = 192_000;

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum CaptureSource {
    System,
    Microphone,
}

impl CaptureSource {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::System => "system",
            Self::Microphone => "microphone",
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StartCaptureRequest {
    pub source: CaptureSource,
    pub device_id: Option<String>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AudioDevice {
    pub id: String,
    pub name: String,
    pub source: CaptureSource,
    pub is_default: bool,
    pub channels: u16,
    pub sample_rate: u32,
    pub native_encoding: String,
    pub buffer_encoding: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AudioFormat {
    pub sample_rate_hz: u32,
    pub channels: u16,
    pub native_encoding: String,
    pub buffer_encoding: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Capability {
    pub source: CaptureSource,
    pub available: bool,
    pub native: bool,
    pub limitation: Option<String>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Capabilities {
    pub platform: String,
    pub system_mix: bool,
    pub per_process_system_audio: bool,
    pub sources: Vec<Capability>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PermissionStatus {
    pub screen_recording: Permission,
    pub microphone: Permission,
    pub notes: Vec<String>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Permission {
    pub state: PermissionState,
    pub can_request: bool,
    pub settings_url: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum PermissionState {
    Granted,
    Denied,
    NotDetermined,
    NotApplicable,
    Unknown,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CaptureStatus {
    pub system: SourceStatus,
    pub microphone: SourceStatus,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SourceStatus {
    pub source: CaptureSource,
    pub running: bool,
    pub frames_buffered: usize,
    pub sample_rate: Option<u32>,
    pub channels: Option<u16>,
    pub native_encoding: Option<String>,
    pub buffer_encoding: Option<String>,
    pub dropped_frames: u64,
    pub error: Option<String>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(tag = "type", rename_all = "camelCase")]
pub enum BackpressureEvent {
    #[serde(rename = "processor", rename_all = "camelCase")]
    Processor {
        meeting_id: String,
        source: Option<CaptureSource>,
        sequence: Option<u64>,
        attempts: u32,
        retry_after_ms: u64,
        message: String,
    },
    #[serde(rename = "captureDrop", rename_all = "camelCase")]
    CaptureDrop {
        source: CaptureSource,
        dropped_frames: u64,
        frames_buffered: usize,
        message: String,
    },
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MeterEvent {
    pub source: CaptureSource,
    pub rms: f32,
    pub peak: f32,
    pub frames_buffered: usize,
    pub timestamp_ms: u128,
}

#[derive(Clone, Copy, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum PermissionKind {
    ScreenRecording,
    Microphone,
    All,
}
