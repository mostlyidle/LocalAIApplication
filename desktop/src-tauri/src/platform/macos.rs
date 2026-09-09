use std::{collections::HashMap, ffi::c_void, process::Command, sync::Arc};

use parking_lot::Mutex;

use super::NativeCapture;
use crate::{
    error::CaptureError,
    model::{
        AudioDevice, Capabilities, Capability, CaptureSource, Permission, PermissionKind,
        PermissionState, PermissionStatus, SourceStatus,
    },
    pcm::PcmRing,
};

// The ScreenCaptureKit Rust integration is intentionally a target dependency pinned to
// screencapturekit 8.0.1 in Cargo.toml. The crate's stream lifetime is hosted by the small
// Objective-C ABI adapter below so the callback can retain PCM in Rust without exposing it.
#[allow(unused_imports)]
use screencapturekit as _screencapturekit_8;

#[repr(C)]
struct NativeCallback {
    queue: Arc<Mutex<PcmRing>>,
}

type PcmCallback = unsafe extern "C" fn(*const f32, u32, u32, u16, *mut c_void);
type ErrorCallback = unsafe extern "C" fn(*const std::ffi::c_char, *mut c_void);

extern "C" {
    fn la_start_system_audio(
        callback: PcmCallback,
        error_callback: ErrorCallback,
        context: *mut c_void,
    ) -> *mut c_void;
    fn la_start_microphone(
        callback: PcmCallback,
        context: *mut c_void,
        sample_rate: *mut u32,
        channels: *mut u16,
    ) -> *mut c_void;
    fn la_stop_capture(handle: *mut c_void) -> i32;
    fn la_screen_recording_permission() -> i32;
    fn la_microphone_permission() -> i32;
    fn la_request_screen_recording_permission() -> i32;
    fn la_request_microphone_permission() -> i32;
}

struct ActiveCapture {
    handle: *mut c_void,
    callback: *mut NativeCallback,
}

unsafe impl Send for ActiveCapture {}

pub struct MacCapture {
    active: Mutex<HashMap<CaptureSource, ActiveCapture>>,
}

impl MacCapture {
    pub fn new() -> Self {
        Self {
            active: Mutex::new(HashMap::new()),
        }
    }
}

unsafe extern "C" fn pcm_callback(
    samples: *const f32,
    count: u32,
    rate: u32,
    channels: u16,
    context: *mut c_void,
) {
    if samples.is_null() || context.is_null() {
        return;
    }
    let callback = &*(context as *const NativeCallback);
    let samples = std::slice::from_raw_parts(samples, count as usize);
    let mut queue = callback.queue.lock();
    queue.set_format(rate, channels, "f32le");
    queue.push_interleaved(samples);
}

unsafe extern "C" fn error_callback(message: *const std::ffi::c_char, context: *mut c_void) {
    if message.is_null() || context.is_null() {
        return;
    }
    let callback = &*(context as *const NativeCallback);
    let message = std::ffi::CStr::from_ptr(message)
        .to_string_lossy()
        .into_owned();
    callback.queue.lock().fail(message);
}

impl NativeCapture for MacCapture {
    fn start(
        &self,
        source: CaptureSource,
        device_id: Option<&str>,
        queue: Arc<Mutex<PcmRing>>,
    ) -> Result<(), CaptureError> {
        let expected_id = match source {
            CaptureSource::System => "system-mix",
            CaptureSource::Microphone => "default-microphone",
        };
        if device_id.is_some_and(|id| id != expected_id) {
            return Err(CaptureError::Device(format!(
                "device '{:?}' is not available on macOS Phase 1",
                device_id
            )));
        }
        if source == CaptureSource::System && unsafe { la_screen_recording_permission() } != 1 {
            return Err(CaptureError::PermissionRequired("Screen Recording".into()));
        }
        if source == CaptureSource::Microphone && unsafe { la_microphone_permission() } != 1 {
            return Err(CaptureError::PermissionRequired("Microphone".into()));
        }
        let status_queue = Arc::clone(&queue);
        let callback = Box::into_raw(Box::new(NativeCallback { queue }));
        let mut sample_rate = 0;
        let mut channels = 0;
        let handle = unsafe {
            match source {
                CaptureSource::System => {
                    la_start_system_audio(pcm_callback, error_callback, callback.cast())
                }
                CaptureSource::Microphone => la_start_microphone(
                    pcm_callback,
                    callback.cast(),
                    &mut sample_rate,
                    &mut channels,
                ),
            }
        };
        if handle.is_null() {
            unsafe {
                drop(Box::from_raw(callback));
            }
            return Err(CaptureError::Native(format!(
                "failed to start {} capture",
                source.as_str()
            )));
        }
        if source == CaptureSource::System {
            // ScreenCaptureKit is configured above with this exact output format. The callback
            // replaces it if the OS reports a route-specific format.
            status_queue.lock().set_format(48_000, 2, "f32le");
        } else if sample_rate != 0 && channels != 0 {
            // AVAudioEngine reports the hardware input format before the first tap callback.
            // Preserve that actual format in status even if the device is initially silent.
            status_queue
                .lock()
                .set_format(sample_rate, channels, "f32le");
            // The callback will also refresh this value if Core Audio changes the route.
        }
        self.active
            .lock()
            .insert(source, ActiveCapture { handle, callback });
        Ok(())
    }

    fn stop(&self, source: CaptureSource) -> Result<(), CaptureError> {
        let Some(active) = self.active.lock().remove(&source) else {
            return Err(CaptureError::NotRunning(source.as_str().into()));
        };
        let result = unsafe { la_stop_capture(active.handle) };
        unsafe {
            drop(Box::from_raw(active.callback));
        }
        if result != 0 {
            return Err(CaptureError::Native(format!(
                "failed to stop {} capture",
                source.as_str()
            )));
        }
        Ok(())
    }

    fn source_status(&self, source: CaptureSource) -> SourceStatus {
        SourceStatus {
            source,
            running: self.active.lock().contains_key(&source),
            frames_buffered: 0,
            sample_rate: None,
            channels: None,
            native_encoding: None,
            buffer_encoding: None,
            dropped_frames: 0,
            error: None,
        }
    }

    fn devices(&self) -> Result<Vec<AudioDevice>, CaptureError> {
        Ok(vec![
            AudioDevice {
                id: "system-mix".into(),
                name: "System Audio Mix".into(),
                source: CaptureSource::System,
                is_default: true,
                channels: 2,
                sample_rate: 48_000,
                native_encoding: "f32le".into(),
                buffer_encoding: "f32le".into(),
            },
            AudioDevice {
                id: "default-microphone".into(),
                name: "Default Microphone".into(),
                source: CaptureSource::Microphone,
                is_default: true,
                channels: 2,
                sample_rate: 48_000,
                native_encoding: "f32le".into(),
                buffer_encoding: "f32le".into(),
            },
        ])
    }
}

impl Drop for MacCapture {
    fn drop(&mut self) {
        for (_, active) in self.active.get_mut().drain() {
            unsafe {
                la_stop_capture(active.handle);
                drop(Box::from_raw(active.callback));
            }
        }
    }
}

pub fn capabilities() -> Capabilities {
    Capabilities {
        platform: "macos".into(),
        system_mix: true,
        per_process_system_audio: false,
        sources: vec![
            Capability { source: CaptureSource::System, available: true, native: true, limitation: Some("ScreenCaptureKit exposes the display system mix; per-process selection is not enabled in Phase 1.".into()) },
            Capability { source: CaptureSource::Microphone, available: true, native: true, limitation: Some("Phase 1 uses the default AVAudioEngine input device.".into()) },
        ],
    }
}

pub fn permissions() -> PermissionStatus {
    let screen = unsafe { la_screen_recording_permission() };
    let microphone = unsafe { la_microphone_permission() };
    PermissionStatus {
        screen_recording: Permission { state: screen_permission(screen), can_request: screen != 1, settings_url: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture".into() },
        microphone: Permission { state: permission(microphone), can_request: microphone == 0, settings_url: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone".into() },
        notes: vec!["System audio is a display-wide mix, not a per-process stream.".into(), "macOS reports Screen Recording as not-granted without distinguishing denial from first use; the state is therefore unknown until the user grants it.".into()],
    }
}

pub fn request_permissions(kind: PermissionKind) -> Result<PermissionStatus, CaptureError> {
    match kind {
        PermissionKind::ScreenRecording | PermissionKind::All => unsafe {
            la_request_screen_recording_permission();
        },
        PermissionKind::Microphone => {}
    }
    if matches!(kind, PermissionKind::Microphone | PermissionKind::All) {
        unsafe {
            la_request_microphone_permission();
        }
    }
    Ok(permissions())
}

pub fn open_permission_settings(kind: PermissionKind) -> Result<(), CaptureError> {
    let url = match kind {
        PermissionKind::ScreenRecording => {
            "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
        }
        PermissionKind::Microphone | PermissionKind::All => {
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"
        }
    };
    Command::new("open")
        .arg(url)
        .spawn()
        .map(|_| ())
        .map_err(|error| {
            CaptureError::Native(format!("could not open Privacy & Security: {error}"))
        })
}

fn screen_permission(value: i32) -> PermissionState {
    if value == 1 {
        PermissionState::Granted
    } else {
        PermissionState::Unknown
    }
}

fn permission(value: i32) -> PermissionState {
    match value {
        1 => PermissionState::Granted,
        2 => PermissionState::Denied,
        0 => PermissionState::NotDetermined,
        _ => PermissionState::Unknown,
    }
}
