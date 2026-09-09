use std::sync::Arc;

use parking_lot::Mutex;

use crate::{
    error::CaptureError,
    model::{
        AudioDevice, Capabilities, CaptureSource, PermissionKind, PermissionStatus, SourceStatus,
    },
    pcm::PcmRing,
};

#[cfg(target_os = "macos")]
mod macos;
#[cfg(target_os = "windows")]
mod windows;

#[cfg(target_os = "macos")]
use macos::MacCapture;
#[cfg(target_os = "windows")]
use windows::WindowsCapture;

pub trait NativeCapture: Send + Sync {
    fn start(
        &self,
        source: CaptureSource,
        device_id: Option<&str>,
        pcm: Arc<Mutex<PcmRing>>,
    ) -> Result<(), CaptureError>;
    fn stop(&self, source: CaptureSource) -> Result<(), CaptureError>;
    fn source_status(&self, source: CaptureSource) -> SourceStatus;
    fn devices(&self) -> Result<Vec<AudioDevice>, CaptureError>;
}

pub fn native_capture() -> Box<dyn NativeCapture> {
    #[cfg(target_os = "macos")]
    {
        return Box::new(MacCapture::new());
    }
    #[cfg(target_os = "windows")]
    {
        return Box::new(WindowsCapture::new());
    }
    #[allow(unreachable_code)]
    Box::new(UnsupportedCapture)
}

pub fn capabilities() -> Capabilities {
    #[cfg(target_os = "macos")]
    {
        return macos::capabilities();
    }
    #[cfg(target_os = "windows")]
    {
        return windows::capabilities();
    }
    #[allow(unreachable_code)]
    Capabilities {
        platform: std::env::consts::OS.to_string(),
        system_mix: false,
        per_process_system_audio: false,
        sources: vec![],
    }
}

pub fn permissions() -> PermissionStatus {
    #[cfg(target_os = "macos")]
    {
        return macos::permissions();
    }
    #[cfg(target_os = "windows")]
    {
        return windows::permissions();
    }
    #[allow(unreachable_code)]
    PermissionStatus {
        screen_recording: crate::model::Permission {
            state: crate::model::PermissionState::NotApplicable,
            can_request: false,
            settings_url: String::new(),
        },
        microphone: crate::model::Permission {
            state: crate::model::PermissionState::Unknown,
            can_request: false,
            settings_url: String::new(),
        },
        notes: vec!["Native capture is not implemented for this target.".into()],
    }
}

pub fn request_permissions(kind: PermissionKind) -> Result<PermissionStatus, CaptureError> {
    #[cfg(target_os = "macos")]
    {
        return macos::request_permissions(kind);
    }
    #[cfg(target_os = "windows")]
    {
        return windows::request_permissions(kind);
    }
    #[allow(unreachable_code)]
    Err(CaptureError::UnsupportedSource("permissions".into()))
}

pub fn open_permission_settings(kind: PermissionKind) -> Result<(), CaptureError> {
    #[cfg(target_os = "macos")]
    {
        return macos::open_permission_settings(kind);
    }
    #[cfg(target_os = "windows")]
    {
        return windows::open_permission_settings(kind);
    }
    #[allow(unreachable_code)]
    Err(CaptureError::UnsupportedSource(
        "permission settings".into(),
    ))
}

struct UnsupportedCapture;

impl NativeCapture for UnsupportedCapture {
    fn start(
        &self,
        source: CaptureSource,
        _: Option<&str>,
        _: Arc<Mutex<PcmRing>>,
    ) -> Result<(), CaptureError> {
        Err(CaptureError::UnsupportedSource(source.as_str().into()))
    }
    fn stop(&self, source: CaptureSource) -> Result<(), CaptureError> {
        Err(CaptureError::NotRunning(source.as_str().into()))
    }
    fn source_status(&self, source: CaptureSource) -> SourceStatus {
        SourceStatus {
            source,
            running: false,
            frames_buffered: 0,
            sample_rate: None,
            channels: None,
            native_encoding: None,
            buffer_encoding: None,
            dropped_frames: 0,
            error: Some("Unsupported platform".into()),
        }
    }
    fn devices(&self) -> Result<Vec<AudioDevice>, CaptureError> {
        Ok(vec![])
    }
}
