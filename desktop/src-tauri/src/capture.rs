use std::{
    collections::HashMap,
    sync::Arc,
    thread,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use parking_lot::Mutex;
use tauri::{AppHandle, Emitter, Runtime};

use crate::{
    error::CaptureError,
    model::{
        AudioDevice, BackpressureEvent, CaptureSource, CaptureStatus, MeterEvent, SourceStatus,
        StartCaptureRequest, BACKPRESSURE_EVENT, METER_EVENT, STATUS_EVENT,
    },
    pcm::{levels, PcmRing},
    platform::{native_capture, NativeCapture},
};

pub struct CaptureManager {
    backend: Box<dyn NativeCapture>,
    queues: HashMap<CaptureSource, Arc<Mutex<PcmRing>>>,
    queue_registry: Arc<Mutex<HashMap<CaptureSource, Arc<Mutex<PcmRing>>>>>,
    errors: HashMap<CaptureSource, String>,
}

impl CaptureManager {
    pub fn new() -> Self {
        Self {
            backend: native_capture(),
            queues: HashMap::new(),
            queue_registry: Arc::new(Mutex::new(HashMap::new())),
            errors: HashMap::new(),
        }
    }

    pub fn devices(&self) -> Result<Vec<AudioDevice>, CaptureError> {
        self.backend.devices()
    }

    pub fn source_queues(&self) -> HashMap<CaptureSource, Arc<Mutex<PcmRing>>> {
        self.queues.clone()
    }

    pub fn shutdown<R: Runtime>(&mut self, app: &AppHandle<R>) {
        let sources: Vec<_> = self.queues.keys().copied().collect();
        for source in sources {
            // Terminal transport cleanup must purge the native queue even if
            // the platform stop call reports an error.  No later transport or
            // frontend command may retain a reference to this session's PCM.
            let _ = self.backend.stop(source);
            if let Some(queue) = self.queues.remove(&source) {
                queue.lock().deactivate();
            }
            self.queue_registry.lock().remove(&source);
        }
        self.emit_status(app);
    }

    /// Drains native PCM for the future direct backend transport. This is intentionally not a
    /// Tauri command and therefore cannot be called by the frontend IPC layer.
    pub fn drain_pcm(&self, source: CaptureSource, max_frames: usize) -> Option<Vec<f32>> {
        self.queues
            .get(&source)
            .map(|queue| queue.lock().drain(max_frames))
    }

    pub fn start<R: Runtime>(
        &mut self,
        app: &AppHandle<R>,
        request: StartCaptureRequest,
    ) -> Result<CaptureStatus, CaptureError> {
        if let Some(queue) = self.queues.get(&request.source) {
            if queue.lock().is_active() {
                return Err(CaptureError::AlreadyRunning(request.source.as_str().into()));
            }
            let _ = self.backend.stop(request.source);
            self.queues.remove(&request.source);
            self.queue_registry.lock().remove(&request.source);
        }
        let queue = Arc::new(Mutex::new(PcmRing::new(2)));
        self.errors.remove(&request.source);
        if let Err(error) = self.backend.start(
            request.source,
            request.device_id.as_deref(),
            Arc::clone(&queue),
        ) {
            let message = error.to_string();
            queue.lock().fail(message.clone());
            self.errors.insert(request.source, message);
            self.emit_status(app);
            return Err(error);
        }
        self.queues.insert(request.source, queue);
        self.queue_registry
            .lock()
            .insert(request.source, self.queues[&request.source].clone());
        self.start_meter_publisher(app, request.source);
        self.emit_status(app);
        Ok(self.status())
    }

    pub fn stop<R: Runtime>(
        &mut self,
        app: &AppHandle<R>,
        source: CaptureSource,
    ) -> Result<CaptureStatus, CaptureError> {
        if !self.queues.contains_key(&source) {
            // Transport shutdown owns the native queues. A subsequent explicit
            // stop from the frontend is an idempotent acknowledgement, not an
            // error for an already-cleaned-up source.
            self.emit_status(app);
            return Ok(self.status());
        }
        if let Err(error) = self.backend.stop(source) {
            let message = error.to_string();
            self.errors.insert(source, message.clone());
            if let Some(queue) = self.queues.get(&source) {
                queue.lock().fail(message);
            }
            self.emit_status(app);
            return Err(error);
        }
        if let Some(queue) = self.queues.remove(&source) {
            queue.lock().deactivate();
        }
        self.queue_registry.lock().remove(&source);
        self.emit_status(app);
        Ok(self.status())
    }

    pub fn status(&self) -> CaptureStatus {
        let status = |source| {
            self.queues.get(&source).map_or_else(
                || {
                    let mut status = self.backend.source_status(source);
                    status.error = self.errors.get(&source).cloned().or(status.error);
                    status
                },
                |queue| {
                    let queue = queue.lock();
                    let mut status = self.backend.source_status(source);
                    status.running = status.running && queue.is_active();
                    status.frames_buffered = queue.frames();
                    status.dropped_frames = queue.dropped_frames();
                    status.error = queue.error();
                    if status.error.is_none() {
                        status.error = self.errors.get(&source).cloned();
                    }
                    if let Some(format) = queue.format() {
                        status.sample_rate = Some(format.sample_rate_hz);
                        status.channels = Some(format.channels);
                        status.native_encoding = Some(format.native_encoding);
                        status.buffer_encoding = Some(format.buffer_encoding);
                    }
                    status
                },
            )
        };
        CaptureStatus {
            system: status(CaptureSource::System),
            microphone: status(CaptureSource::Microphone),
        }
    }

    fn emit_status<R: Runtime>(&self, app: &AppHandle<R>) {
        let _ = app.emit(STATUS_EVENT, self.status());
    }

    fn start_meter_publisher<R: Runtime>(&self, app: &AppHandle<R>, source: CaptureSource) {
        let Some(queue) = self.queues.get(&source).cloned() else {
            return;
        };
        let queue_registry = Arc::clone(&self.queue_registry);
        let app = app.clone();
        thread::Builder::new()
            .name(format!("localai-meter-{}", source.as_str()))
            .spawn(move || {
                let mut last_dropped_frames = 0;
                loop {
                thread::sleep(Duration::from_millis(100));
                if queue.lock().error().is_some() {
                    let _ = app.emit(STATUS_EVENT, status_from_registry(&queue_registry));
                    break;
                }
                let (samples, frames_buffered, active, dropped_frames) = {
                    let queue = queue.lock();
                    (
                        queue.meter_samples(),
                        queue.frames(),
                        queue.is_active(),
                        queue.dropped_frames(),
                    )
                };
                if dropped_frames > last_dropped_frames {
                    let _ = app.emit(
                        BACKPRESSURE_EVENT,
                        BackpressureEvent::CaptureDrop {
                            source,
                            dropped_frames,
                            frames_buffered,
                            message: "Native capture dropped audio frames; oldest buffered audio was discarded.".into(),
                        },
                    );
                    let _ = app.emit(STATUS_EVENT, status_from_registry(&queue_registry));
                    last_dropped_frames = dropped_frames;
                }
                if !active {
                    break;
                }
                let (rms, peak) = levels(&samples);
                let event = MeterEvent {
                    source,
                    rms,
                    peak,
                    frames_buffered,
                    timestamp_ms: SystemTime::now()
                        .duration_since(UNIX_EPOCH)
                        .map_or(0, |duration| duration.as_millis()),
                };
                let _ = app.emit(METER_EVENT, event);
                }
            })
            .ok();
    }
}

fn source_status_from_queue(source: CaptureSource, queue: &PcmRing) -> SourceStatus {
    let format = queue.format();
    SourceStatus {
        source,
        running: queue.is_active(),
        frames_buffered: queue.frames(),
        sample_rate: format.as_ref().map(|value| value.sample_rate_hz),
        channels: format.as_ref().map(|value| value.channels),
        native_encoding: format.as_ref().map(|value| value.native_encoding.clone()),
        buffer_encoding: format.map(|value| value.buffer_encoding),
        dropped_frames: queue.dropped_frames(),
        error: queue.error(),
    }
}

fn status_from_registry(
    registry: &Arc<Mutex<HashMap<CaptureSource, Arc<Mutex<PcmRing>>>>>,
) -> CaptureStatus {
    let stopped = |other| SourceStatus {
        source: other,
        running: false,
        frames_buffered: 0,
        sample_rate: None,
        channels: None,
        native_encoding: None,
        buffer_encoding: None,
        dropped_frames: 0,
        error: None,
    };
    let registry = registry.lock();
    let system = registry.get(&CaptureSource::System).map_or_else(
        || stopped(CaptureSource::System),
        |queue| source_status_from_queue(CaptureSource::System, &queue.lock()),
    );
    let microphone = registry.get(&CaptureSource::Microphone).map_or_else(
        || stopped(CaptureSource::Microphone),
        |queue| source_status_from_queue(CaptureSource::Microphone, &queue.lock()),
    );
    CaptureStatus { system, microphone }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shutdown_then_stop_capture_is_idempotent() {
        let app = tauri::test::mock_app();
        let handle = app.handle().clone();
        let source = CaptureSource::Microphone;
        let mut manager = CaptureManager::new();
        let queue = Arc::new(Mutex::new(PcmRing::new(1)));
        manager.queues.insert(source, Arc::clone(&queue));
        manager.queue_registry.lock().insert(source, queue);

        manager.shutdown(&handle);
        assert!(!manager.status().microphone.running);
        assert!(!manager.stop(&handle, source).unwrap().microphone.running);

        // A second transport-owned cleanup is also harmless.
        manager.shutdown(&handle);
        assert!(manager.stop(&handle, source).is_ok());
    }

    #[test]
    fn capture_drop_event_serializes_counter_for_frontend_ipc() {
        let event = BackpressureEvent::CaptureDrop {
            source: CaptureSource::System,
            dropped_frames: 12,
            frames_buffered: 48,
            message: "audio dropped".into(),
        };
        let payload = serde_json::to_value(event).unwrap();
        assert_eq!(payload["type"], "captureDrop");
        assert_eq!(payload["source"], "system");
        assert_eq!(payload["droppedFrames"], 12);
    }
}
