mod capture;
mod error;
pub mod model;
pub mod pcm;
mod platform;
pub mod transport;
mod worker;

use capture::CaptureManager;
use error::{CaptureError, CommandError};
use model::{
    AudioDevice, Capabilities, CaptureSource, CaptureStatus, PermissionKind, PermissionStatus,
    StartCaptureRequest,
};
use parking_lot::Mutex;
use std::sync::Arc;
use tauri::State;
use worker::{TransportRequest, TransportStatus, TransportWorker};

#[tauri::command]
fn get_capabilities() -> Capabilities {
    platform::capabilities()
}

#[tauri::command]
fn get_permissions() -> PermissionStatus {
    platform::permissions()
}

#[tauri::command]
fn list_audio_devices(
    state: State<'_, Arc<Mutex<CaptureManager>>>,
) -> Result<Vec<AudioDevice>, CommandError> {
    state.lock().devices().map_err(Into::into)
}

#[tauri::command]
async fn start_capture(
    app: tauri::AppHandle,
    state: State<'_, Arc<Mutex<CaptureManager>>>,
    request: StartCaptureRequest,
) -> Result<CaptureStatus, CommandError> {
    if request.device_id.as_ref().is_some_and(|id| id.len() > 256) {
        return Err(error::CaptureError::InvalidRequest("device_id is too long".into()).into());
    }
    let state = Arc::clone(state.inner());
    tauri::async_runtime::spawn_blocking(move || state.lock().start(&app, request))
        .await
        .map_err(|error| {
            CommandError::from(CaptureError::Native(format!(
                "capture worker failed: {error}"
            )))
        })?
        .map_err(Into::into)
}

#[tauri::command]
async fn stop_capture(
    app: tauri::AppHandle,
    state: State<'_, Arc<Mutex<CaptureManager>>>,
    source: CaptureSource,
) -> Result<CaptureStatus, CommandError> {
    let state = Arc::clone(state.inner());
    tauri::async_runtime::spawn_blocking(move || state.lock().stop(&app, source))
        .await
        .map_err(|error| {
            CommandError::from(CaptureError::Native(format!(
                "capture worker failed: {error}"
            )))
        })?
        .map_err(Into::into)
}

#[tauri::command]
fn get_capture_status(state: State<'_, Arc<Mutex<CaptureManager>>>) -> CaptureStatus {
    state.lock().status()
}

#[tauri::command]
fn start_meeting_transport(
    app: tauri::AppHandle,
    capture: State<'_, Arc<Mutex<CaptureManager>>>,
    worker: State<'_, Arc<Mutex<TransportWorker>>>,
    request: TransportRequest,
) -> Result<TransportStatus, CommandError> {
    worker
        .lock()
        .start(request, app, Arc::clone(capture.inner()))
        .map_err(Into::into)
}

#[tauri::command]
fn stop_meeting_transport(worker: State<'_, Arc<Mutex<TransportWorker>>>) -> TransportStatus {
    worker.lock().stop()
}

#[tauri::command]
fn get_meeting_transport_status(worker: State<'_, Arc<Mutex<TransportWorker>>>) -> TransportStatus {
    worker.lock().status()
}

#[tauri::command]
async fn request_permissions(kind: PermissionKind) -> Result<PermissionStatus, CommandError> {
    tauri::async_runtime::spawn_blocking(move || platform::request_permissions(kind))
        .await
        .map_err(|error| {
            CommandError::from(CaptureError::Native(format!(
                "permission worker failed: {error}"
            )))
        })?
        .map_err(Into::into)
}

#[tauri::command]
fn open_permission_settings(kind: PermissionKind) -> Result<(), CommandError> {
    platform::open_permission_settings(kind).map_err(Into::into)
}

pub fn run() {
    tauri::Builder::default()
        .manage(Arc::new(Mutex::new(CaptureManager::new())))
        .manage(Arc::new(Mutex::new(TransportWorker::new())))
        .invoke_handler(tauri::generate_handler![
            get_capabilities,
            get_permissions,
            list_audio_devices,
            start_capture,
            stop_capture,
            get_capture_status,
            request_permissions,
            open_permission_settings,
            start_meeting_transport,
            stop_meeting_transport,
            get_meeting_transport_status
        ])
        .run(tauri::generate_context!())
        .expect("error while running Local AI desktop application");
}
