use serde::Serialize;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum CaptureError {
    #[error("capture is already running for source '{0}'")]
    AlreadyRunning(String),
    #[error("capture is not running for source '{0}'")]
    NotRunning(String),
    #[error("source '{0}' is not available on this platform")]
    UnsupportedSource(String),
    #[error("native permission is required for {0}")]
    PermissionRequired(String),
    #[error("native audio device error: {0}")]
    Device(String),
    #[error("native capture error: {0}")]
    Native(String),
    #[error("invalid capture request: {0}")]
    InvalidRequest(String),
    #[error("capture service lock is unavailable")]
    StateUnavailable,
}

#[derive(Debug, Serialize)]
pub struct CommandError {
    pub code: &'static str,
    pub message: String,
}

impl From<CaptureError> for CommandError {
    fn from(error: CaptureError) -> Self {
        let code = match &error {
            CaptureError::AlreadyRunning(_) => "already_running",
            CaptureError::NotRunning(_) => "not_running",
            CaptureError::UnsupportedSource(_) => "unsupported_source",
            CaptureError::PermissionRequired(_) => "permission_required",
            CaptureError::Device(_) => "device_error",
            CaptureError::Native(_) => "native_error",
            CaptureError::InvalidRequest(_) => "invalid_request",
            CaptureError::StateUnavailable => "state_unavailable",
        };
        Self {
            code,
            message: error.to_string(),
        }
    }
}
