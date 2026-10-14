use std::{
    collections::{BTreeMap, HashMap, HashSet, VecDeque},
    io::ErrorKind,
    net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr, TcpStream},
    sync::{
        mpsc::{self, Receiver, Sender},
        Arc,
    },
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter};
use tungstenite::stream::MaybeTlsStream;
use tungstenite::{
    client::{client, IntoClientRequest},
    Error as WebSocketError, Message, WebSocket,
};
use url::Url;

use crate::{
    capture::CaptureManager,
    error::CaptureError,
    model::{BackpressureEvent, CaptureSource, BACKPRESSURE_EVENT},
    transport::build_audio_envelope,
};

pub const BACKEND_EVENT: &str = "meeting://backend-event";
pub const TRANSPORT_STATUS_EVENT: &str = "meeting://transport-status";
pub const MEETING_STATUS_EVENT: &str = "meeting://status";
pub const SOURCE_STATUS_EVENT: &str = "meeting://source-status";
pub const TRANSCRIPT_EVENT: &str = "meeting://transcript";
pub const QUESTION_EVENT: &str = "meeting://question";
pub const ANSWER_EVENT: &str = "meeting://answer";
pub const DEGRADED_EVENT: &str = "meeting://degraded";
const ORIGIN: &str = "tauri://localhost";
const MAX_IN_FLIGHT_PER_SOURCE: usize = 1;
const MAX_RECONNECT_ATTEMPTS: u32 = 5;
const CHUNK_FRAMES: usize = 960;
const MAX_MEETING_ID_BYTES: usize = 36;
const BACKPRESSURE_BASE_BACKOFF_MS: u64 = 25;
const BACKPRESSURE_MAX_BACKOFF_MS: u64 = 500;
const RECONNECT_STABILITY_WINDOW: Duration = Duration::from_secs(1);
const STOP_DRAIN_TIMEOUT: Duration = Duration::from_secs(2);
const STOP_AUDIO_DRAIN_TIMEOUT: Duration = Duration::from_secs(2);
const CONNECT_TIMEOUT: Duration = Duration::from_millis(250);
const HANDSHAKE_TIMEOUT: Duration = Duration::from_millis(500);
const SOCKET_READ_TIMEOUT: Duration = Duration::from_millis(25);
const SOCKET_WRITE_TIMEOUT: Duration = Duration::from_millis(500);

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TransportRequest {
    pub meeting_id: String,
    pub backend_url: String,
    pub stream_ticket: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum TransportPhase {
    Stopped,
    Connecting,
    Active,
    Stopping,
    Failed,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TransportStatus {
    pub phase: TransportPhase,
    pub meeting_id: Option<String>,
    pub reconnect_attempts: u32,
    pub error: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
enum ControlMessage {
    #[serde(rename = "start")]
    Start,
    #[serde(rename = "stop")]
    Stop,
    #[serde(rename = "source_ended")]
    SourceEnded { source: CaptureSource },
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
pub enum BackendEvent {
    #[serde(rename = "status")]
    Status { status: String, meeting_id: String },
    #[serde(rename = "source_status")]
    SourceStatus {
        meeting_id: String,
        source: CaptureSource,
        status: String,
    },
    #[serde(rename = "ack")]
    Ack {
        source: CaptureSource,
        sequence: u64,
        #[serde(default)]
        duplicate: bool,
    },
    #[serde(rename = "error")]
    Error {
        code: String,
        message: String,
        sequence: Option<u64>,
    },
    #[serde(rename = "transcript")]
    Transcript {
        meeting_id: String,
        segment_id: String,
        source: CaptureSource,
        text: String,
        start_ms: i64,
        end_ms: i64,
        #[serde(rename = "final", default = "default_true")]
        final_event: bool,
    },
    #[serde(rename = "question")]
    Question {
        meeting_id: String,
        question_id: String,
        #[serde(default = "default_system_source")]
        source: CaptureSource,
        text: String,
    },
    #[serde(rename = "answer")]
    Answer {
        meeting_id: String,
        question_id: String,
        answer: String,
        #[serde(default)]
        citations: Vec<String>,
    },
    #[serde(rename = "degraded")]
    Degraded {
        meeting_id: String,
        component: String,
        message: String,
    },
}

enum WorkerCommand {
    Stop,
    Shutdown,
}

pub struct TransportWorker {
    control: Option<Sender<WorkerCommand>>,
    thread: Option<thread::JoinHandle<()>>,
    status: Arc<Mutex<TransportStatus>>,
}

impl TransportWorker {
    pub fn new() -> Self {
        Self {
            control: None,
            thread: None,
            status: Arc::new(Mutex::new(TransportStatus {
                phase: TransportPhase::Stopped,
                meeting_id: None,
                reconnect_attempts: 0,
                error: None,
            })),
        }
    }

    pub fn status(&self) -> TransportStatus {
        self.status.lock().clone()
    }

    pub fn start(
        &mut self,
        request: TransportRequest,
        app: AppHandle,
        capture: Arc<Mutex<CaptureManager>>,
    ) -> Result<TransportStatus, CaptureError> {
        validate_request(&request)?;
        self.reap_finished();
        if matches!(
            self.status.lock().phase,
            TransportPhase::Connecting | TransportPhase::Active | TransportPhase::Stopping
        ) {
            return Err(CaptureError::AlreadyRunning("meeting transport".into()));
        }
        let queues = capture.lock().source_queues();
        if queues.values().all(|queue| !queue.lock().is_active()) {
            return Err(CaptureError::InvalidRequest(
                "at least one native capture source must be running".into(),
            ));
        }
        let (sender, receiver) = mpsc::channel();
        let status = Arc::clone(&self.status);
        *status.lock() = TransportStatus {
            phase: TransportPhase::Connecting,
            meeting_id: Some(request.meeting_id.clone()),
            reconnect_attempts: 0,
            error: None,
        };
        emit_status(&app, &status);
        let thread_status = Arc::clone(&status);
        let worker_app = app.clone();
        let handle = match thread::Builder::new()
            .name("localai-meeting-transport".into())
            .spawn(move || {
                run_worker(
                    request,
                    worker_app,
                    capture,
                    queues,
                    receiver,
                    thread_status,
                )
            }) {
            Ok(handle) => handle,
            Err(error) => {
                let message = format!("could not start transport worker: {error}");
                set_phase(
                    &app,
                    &status,
                    TransportPhase::Stopped,
                    0,
                    Some(message.clone()),
                );
                return Err(CaptureError::Native(message));
            }
        };
        self.control = Some(sender);
        self.thread = Some(handle);
        Ok(self.status())
    }

    pub fn stop(&mut self) -> TransportStatus {
        self.reap_finished();
        let Some(sender) = &self.control else {
            return self.status();
        };
        let _ = sender.send(WorkerCommand::Stop);
        {
            self.status.lock().phase = TransportPhase::Stopping;
        }
        if let Some(handle) = self.thread.take() {
            let _ = handle.join();
            self.control = None;
        }
        self.status()
    }
}

impl Drop for TransportWorker {
    fn drop(&mut self) {
        if let Some(sender) = self.control.take() {
            let _ = sender.send(WorkerCommand::Shutdown);
        }
        if let Some(handle) = self.thread.take() {
            let _ = handle.join();
        }
    }
}

impl TransportWorker {
    fn reap_finished(&mut self) {
        let finished = self
            .thread
            .as_ref()
            .is_some_and(thread::JoinHandle::is_finished);
        if finished {
            if let Some(handle) = self.thread.take() {
                let _ = handle.join();
            }
            self.control = None;
        }
    }
}

fn validate_request(request: &TransportRequest) -> Result<(), CaptureError> {
    if request.meeting_id.is_empty()
        || request.meeting_id.len() > MAX_MEETING_ID_BYTES
        || request
            .meeting_id
            .chars()
            .any(|c| c == '/' || c == '?' || c == '#' || c.is_control())
    {
        return Err(CaptureError::InvalidRequest("meeting_id is invalid".into()));
    }
    if !(32..=128).contains(&request.stream_ticket.len())
        || !request
            .stream_ticket
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || matches!(character, '-' | '_'))
    {
        return Err(CaptureError::InvalidRequest(
            "stream_ticket is invalid".into(),
        ));
    }
    let url = Url::parse(&request.backend_url).map_err(|error| {
        CaptureError::InvalidRequest(format!("backend_url is invalid: {error}"))
    })?;
    if url.scheme() != "http"
        || !matches!(url.host_str(), Some("localhost" | "127.0.0.1" | "::1"))
        || url.username() != ""
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err(CaptureError::InvalidRequest(
            "backend_url must be a localhost HTTP URL without credentials or query parameters"
                .into(),
        ));
    }
    Ok(())
}

fn run_worker(
    request: TransportRequest,
    app: AppHandle,
    capture: Arc<Mutex<CaptureManager>>,
    queues: HashMap<CaptureSource, Arc<Mutex<crate::pcm::PcmRing>>>,
    receiver: Receiver<WorkerCommand>,
    status: Arc<Mutex<TransportStatus>>,
) {
    let mut attempts = 0;
    let mut sequence = HashMap::<CaptureSource, u64>::new();
    let mut stop_requested = false;
    let mut stop_deadline = None;
    loop {
        if !stop_requested && command_pending(&receiver) {
            begin_stop(&app, &capture, &mut stop_requested, &mut stop_deadline);
        }
        set_phase(&app, &status, TransportPhase::Connecting, attempts, None);
        match connect_socket(&request) {
            Ok(mut socket) => {
                let connected_at = Instant::now();
                set_phase(&app, &status, TransportPhase::Active, attempts, None);
                match run_session(
                    &mut socket,
                    &request,
                    &app,
                    &queues,
                    &receiver,
                    &mut sequence,
                    &capture,
                    &mut stop_requested,
                    &mut stop_deadline,
                ) {
                    SessionResult::Stop(stop_warning) => {
                        let _ = socket.send(control(ControlMessage::Stop));
                        let server_drain_error = (!drain_after_stop(&mut socket, &app)).then(|| {
                            "backend stopped status was not received before timeout".into()
                        });
                        finish(
                            &app,
                            &capture,
                            &status,
                            false,
                            stop_warning.or(server_drain_error),
                        );
                        return;
                    }
                    SessionResult::Reconnect(error) => {
                        attempts = reconnect_attempts(
                            attempts,
                            Instant::now().duration_since(connected_at),
                        );
                        if attempts > MAX_RECONNECT_ATTEMPTS {
                            finish(&app, &capture, &status, true, Some(error));
                            return;
                        }
                    }
                    SessionResult::Terminal(error) => {
                        let _ = socket.send(control(ControlMessage::Stop));
                        finish(&app, &capture, &status, true, Some(error));
                        return;
                    }
                }
            }
            Err(error) => {
                attempts = attempts.saturating_add(1);
                if attempts > MAX_RECONNECT_ATTEMPTS {
                    finish(&app, &capture, &status, true, Some(error.to_string()));
                    return;
                }
            }
        }
        set_phase(&app, &status, TransportPhase::Connecting, attempts, None);
        if !stop_requested {
            match receiver.recv_timeout(Duration::from_millis(
                (100 * 2_u64.pow(attempts.min(4))).min(2_000),
            )) {
                Ok(_) | Err(mpsc::RecvTimeoutError::Disconnected) => {
                    begin_stop(&app, &capture, &mut stop_requested, &mut stop_deadline);
                }
                Err(mpsc::RecvTimeoutError::Timeout) => {}
            }
        }
    }
}

fn connect_socket(
    request: &TransportRequest,
) -> Result<WebSocket<MaybeTlsStream<TcpStream>>, WorkerError> {
    let base = Url::parse(&request.backend_url)
        .map_err(|error| WorkerError::Connection(error.to_string()))?;
    let mut websocket_url = base;
    websocket_url
        .set_scheme("ws")
        .map_err(|_| WorkerError::Connection("could not construct websocket URL".into()))?;
    websocket_url.set_path(&format!("/api/v1/meetings/{}/stream", request.meeting_id));
    let mut handshake = websocket_url
        .as_str()
        .into_client_request()
        .map_err(|error| WorkerError::Connection(error.to_string()))?;
    handshake.headers_mut().insert(
        "Origin",
        tungstenite::http::HeaderValue::from_static(ORIGIN),
    );
    let ticket = tungstenite::http::HeaderValue::from_str(&request.stream_ticket)
        .map_err(|error| WorkerError::Connection(error.to_string()))?;
    handshake
        .headers_mut()
        .insert("x-meeting-stream-ticket", ticket);
    let port = websocket_url
        .port_or_known_default()
        .ok_or_else(|| WorkerError::Connection("backend URL has no usable port".into()))?;
    let addresses = local_backend_addresses(websocket_url.host_str(), port)?;
    let mut last_error = None;
    for address in addresses {
        let stream = match TcpStream::connect_timeout(&address, CONNECT_TIMEOUT) {
            Ok(stream) => stream,
            Err(error) => {
                last_error = Some(error.to_string());
                continue;
            }
        };
        stream
            .set_read_timeout(Some(HANDSHAKE_TIMEOUT))
            .map_err(|error| WorkerError::Connection(error.to_string()))?;
        stream
            .set_write_timeout(Some(HANDSHAKE_TIMEOUT))
            .map_err(|error| WorkerError::Connection(error.to_string()))?;
        let (mut socket, _) = client(handshake.clone(), MaybeTlsStream::Plain(stream))
            .map_err(|error| WorkerError::Connection(error.to_string()))?;
        set_socket_timeouts(&mut socket)?;
        return Ok(socket);
    }
    Err(WorkerError::Connection(format!(
        "could not connect to local backend: {}",
        last_error.unwrap_or_else(|| "no local address".into())
    )))
}

fn local_backend_addresses(host: Option<&str>, port: u16) -> Result<Vec<SocketAddr>, WorkerError> {
    match host {
        Some("localhost") => Ok(vec![
            SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), port),
            SocketAddr::new(IpAddr::V6(Ipv6Addr::LOCALHOST), port),
        ]),
        Some("127.0.0.1") => Ok(vec![SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), port)]),
        Some("::1") => Ok(vec![SocketAddr::new(IpAddr::V6(Ipv6Addr::LOCALHOST), port)]),
        _ => Err(WorkerError::Connection(
            "backend URL must resolve to localhost".into(),
        )),
    }
}

fn set_socket_timeouts(
    socket: &mut WebSocket<MaybeTlsStream<TcpStream>>,
) -> Result<(), WorkerError> {
    match socket.get_mut() {
        MaybeTlsStream::Plain(stream) => {
            stream
                .set_read_timeout(Some(SOCKET_READ_TIMEOUT))
                .map_err(|error| WorkerError::Connection(error.to_string()))?;
            stream
                .set_write_timeout(Some(SOCKET_WRITE_TIMEOUT))
                .map_err(|error| WorkerError::Connection(error.to_string()))?;
        }
        _ => {}
    }
    Ok(())
}

enum SessionResult {
    Stop(Option<String>),
    Reconnect(String),
    Terminal(String),
}

struct PendingChunk {
    frame_count: usize,
    acknowledged: bool,
}

struct BackpressureRetry {
    attempts: u32,
    retry_at: Instant,
}

struct BackpressureRetryNotice {
    source: CaptureSource,
    sequence: u64,
    attempts: u32,
    retry_after_ms: u64,
}

fn run_session(
    socket: &mut WebSocket<MaybeTlsStream<TcpStream>>,
    request: &TransportRequest,
    app: &AppHandle,
    queues: &HashMap<CaptureSource, Arc<Mutex<crate::pcm::PcmRing>>>,
    receiver: &Receiver<WorkerCommand>,
    sequence: &mut HashMap<CaptureSource, u64>,
    capture: &Arc<Mutex<CaptureManager>>,
    stop_requested: &mut bool,
    stop_deadline: &mut Option<Instant>,
) -> SessionResult {
    if let Err(error) = socket.send(control(ControlMessage::Start)) {
        return SessionResult::Reconnect(error.to_string());
    }
    let mut pending = HashMap::<CaptureSource, BTreeMap<u64, PendingChunk>>::new();
    let mut backpressure_retries = HashMap::<CaptureSource, BackpressureRetry>::new();
    let mut sent_order = VecDeque::<(CaptureSource, u64)>::new();
    let mut ended = HashSet::new();
    loop {
        if !*stop_requested && command_pending(receiver) {
            begin_stop(&app, capture, stop_requested, stop_deadline);
        }
        if stop_deadline.is_some_and(|deadline| Instant::now() >= deadline) {
            return SessionResult::Stop(Some(
                "Some captured audio could not be delivered before the stop timeout.".into(),
            ));
        }
        for (&source, queue) in queues {
            let (error, active) = {
                let queue = queue.lock();
                (queue.error(), queue.is_active())
            };
            if let Some(error) = error {
                return SessionResult::Terminal(format!(
                    "{} capture failed: {error}",
                    source.as_str()
                ));
            }
            let pending_frames = pending
                .get(&source)
                .map(|chunks| chunks.values().map(|chunk| chunk.frame_count).sum())
                .unwrap_or(0);
            if !active && pending_frames == 0 && queue.lock().frames() == 0 && ended.insert(source)
            {
                if let Err(error) = socket.send(control(ControlMessage::SourceEnded { source })) {
                    reset_sequences_for_reconnect(sequence, &pending);
                    return SessionResult::Reconnect(error.to_string());
                }
            }
            if ended.contains(&source)
                || pending.get(&source).map_or(0, BTreeMap::len) >= MAX_IN_FLIGHT_PER_SOURCE
                || backpressure_retries
                    .get(&source)
                    .is_some_and(|retry| Instant::now() < retry.retry_at)
            {
                continue;
            }
            let Some((samples, format, frame_count)) = peek_chunk(queue, pending_frames) else {
                continue;
            };
            let seq = *sequence.entry(source).or_insert(0);
            let timestamp = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_or(1, |value| value.as_nanos().min(u128::from(u64::MAX)) as u64)
                .max(1);
            let envelope = match build_audio_envelope(
                &request.meeting_id,
                source,
                seq,
                timestamp,
                format.sample_rate_hz,
                format.channels,
                &samples,
            ) {
                Ok(value) => value,
                Err(error) => return SessionResult::Terminal(error.to_string()),
            };
            if let Err(error) = socket.send(Message::Binary(envelope.into())) {
                reset_sequences_for_reconnect(sequence, &pending);
                return SessionResult::Reconnect(error.to_string());
            }
            sent_order.push_back((source, seq));
            pending.entry(source).or_default().insert(
                seq,
                PendingChunk {
                    frame_count,
                    acknowledged: false,
                },
            );
            sequence.insert(source, seq + 1);
        }
        if *stop_requested
            && ended.len() == queues.len()
            && pending.values().all(BTreeMap::is_empty)
        {
            return SessionResult::Stop(None);
        }
        match socket.read() {
            Ok(Message::Text(text)) => match serde_json::from_str::<BackendEvent>(&text) {
                Ok(event) => {
                    let terminal = backend_event_terminal(&event);
                    let active_session_conflict = backend_event_retryable(&event);
                    let backpressure = matches!(
                        &event,
                        BackendEvent::Error { code, .. }
                            if code == "AUDIO_PROCESSOR_BACKPRESSURE"
                    );
                    let backpressure_sequence = match &event {
                        BackendEvent::Error {
                            code,
                            sequence: error_sequence,
                            ..
                        } if code == "AUDIO_PROCESSOR_BACKPRESSURE" => *error_sequence,
                        _ => None,
                    };
                    let ack = match &event {
                        BackendEvent::Ack {
                            source, sequence, ..
                        } => Some((*source, *sequence)),
                        _ => None,
                    };
                    emit_backend_event(app, event.clone());
                    if active_session_conflict {
                        reset_sequences_for_reconnect(sequence, &pending);
                        return SessionResult::Reconnect(
                            "backend audio session is still transitioning".into(),
                        );
                    }
                    if let Some(error) = terminal {
                        return SessionResult::Terminal(error);
                    }
                    if backpressure {
                        let retry = schedule_backpressure_retry(
                            &mut pending,
                            sequence,
                            &mut backpressure_retries,
                            &mut sent_order,
                            backpressure_sequence,
                            Instant::now(),
                        );
                        let (source, sequence, attempts, retry_after_ms) =
                            retry
                                .as_ref()
                                .map_or((None, backpressure_sequence, 0, 0), |notice| {
                                    (
                                        Some(notice.source),
                                        Some(notice.sequence),
                                        notice.attempts,
                                        notice.retry_after_ms,
                                    )
                                });
                        let message = match &event {
                            BackendEvent::Error { message, .. } => message.clone(),
                            _ => "Audio processor backpressure; retrying the same chunk.".into(),
                        };
                        let _ = app.emit(
                            BACKPRESSURE_EVENT,
                            BackpressureEvent::Processor {
                                meeting_id: request.meeting_id.clone(),
                                source,
                                sequence,
                                attempts,
                                retry_after_ms,
                                message,
                            },
                        );
                    }
                    if let Some((source, sequence)) = ack {
                        sent_order.retain(|entry| *entry != (source, sequence));
                        if let Some(values) = pending.get_mut(&source) {
                            if let Some(chunk) = values.get_mut(&sequence) {
                                chunk.acknowledged = true;
                            }
                            while values
                                .first_key_value()
                                .is_some_and(|(_, chunk)| chunk.acknowledged)
                            {
                                let (_, chunk) = values.pop_first().expect("pending chunk exists");
                                if let Some(queue) = queues.get(&source) {
                                    queue.lock().drain(chunk.frame_count);
                                }
                            }
                            if values.is_empty() {
                                pending.remove(&source);
                            }
                            backpressure_retries.remove(&source);
                        }
                    }
                }
                Err(error) => {
                    return SessionResult::Terminal(format!("invalid backend event: {error}"))
                }
            },
            Ok(Message::Close(_)) => {
                reset_sequences_for_reconnect(sequence, &pending);
                return SessionResult::Reconnect("backend websocket closed".into());
            }
            Ok(_) => {}
            Err(WebSocketError::Io(error))
                if matches!(error.kind(), ErrorKind::WouldBlock | ErrorKind::TimedOut) => {}
            Err(WebSocketError::ConnectionClosed) => {
                reset_sequences_for_reconnect(sequence, &pending);
                return SessionResult::Reconnect("backend websocket closed".into());
            }
            Err(error) => {
                reset_sequences_for_reconnect(sequence, &pending);
                return SessionResult::Reconnect(error.to_string());
            }
        }
        thread::sleep(Duration::from_millis(5));
    }
}

fn reset_sequences_for_reconnect(
    sequence: &mut HashMap<CaptureSource, u64>,
    pending: &HashMap<CaptureSource, BTreeMap<u64, PendingChunk>>,
) {
    let sources: HashSet<_> = sequence.keys().chain(pending.keys()).copied().collect();
    for source in sources {
        // The backend purges its processor session when the socket closes, so
        // every source in the new session starts at zero. Unacknowledged PCM is
        // still at the head of its native queue and is retransmitted there.
        sequence.insert(source, 0);
    }
}

fn peek_chunk(
    queue: &Arc<Mutex<crate::pcm::PcmRing>>,
    offset_frames: usize,
) -> Option<(Vec<f32>, crate::model::AudioFormat, usize)> {
    let queue = queue.lock();
    let format = queue.format()?;
    let channels = usize::from(format.channels);
    let samples = queue.peek_from(offset_frames, CHUNK_FRAMES);
    if samples.is_empty() {
        return None;
    }
    let frame_count = samples.len() / channels;
    Some((samples, format, frame_count))
}

fn control(value: ControlMessage) -> Message {
    Message::Text(
        serde_json::to_string(&value)
            .expect("control messages are serializable")
            .into(),
    )
}

fn drain_after_stop(socket: &mut WebSocket<MaybeTlsStream<TcpStream>>, app: &AppHandle) -> bool {
    let deadline = Instant::now() + STOP_DRAIN_TIMEOUT;
    loop {
        if Instant::now() >= deadline {
            return false;
        }
        match socket.read() {
            Ok(Message::Text(text)) => match serde_json::from_str::<BackendEvent>(&text) {
                Ok(event) => {
                    let stopped = matches!(
                        &event,
                        BackendEvent::Status { status, .. } if status == "stopped"
                    );
                    emit_backend_event(app, event);
                    if stopped {
                        return true;
                    }
                }
                Err(_) => {}
            },
            Ok(Message::Close(_)) | Err(WebSocketError::ConnectionClosed) => return false,
            Ok(_) => {}
            Err(WebSocketError::Io(error))
                if matches!(error.kind(), ErrorKind::WouldBlock | ErrorKind::TimedOut) => {}
            Err(_) => return false,
        }
    }
}

fn backend_event_terminal(event: &BackendEvent) -> Option<String> {
    match event {
        BackendEvent::Status { status, .. } if status == "failed" => {
            Some("backend meeting failed".into())
        }
        BackendEvent::Status { status, .. } if status == "stopped" => {
            Some("backend meeting stopped".into())
        }
        BackendEvent::Error { code, message, .. }
            if code == "ORIGIN_NOT_ALLOWED"
                || code.starts_with("MEETING_")
                || code == "AUDIO_SESSION_NOT_ACTIVE" =>
        {
            Some(message.clone())
        }
        _ => None,
    }
}

fn backend_event_retryable(event: &BackendEvent) -> bool {
    matches!(
        event,
        BackendEvent::Error { code, .. } if code == "ACTIVE_AUDIO_SESSION"
    )
}

fn reconnect_attempts(previous: u32, connected_for: Duration) -> u32 {
    if connected_for >= RECONNECT_STABILITY_WINDOW {
        1
    } else {
        previous.saturating_add(1)
    }
}

fn backpressure_delay(attempt: u32) -> Duration {
    let shift = attempt.saturating_sub(1).min(5);
    let multiplier = 1_u64 << shift;
    Duration::from_millis(
        BACKPRESSURE_BASE_BACKOFF_MS
            .saturating_mul(multiplier)
            .min(BACKPRESSURE_MAX_BACKOFF_MS),
    )
}

fn schedule_backpressure_retry(
    pending: &mut HashMap<CaptureSource, BTreeMap<u64, PendingChunk>>,
    sequence: &mut HashMap<CaptureSource, u64>,
    retries: &mut HashMap<CaptureSource, BackpressureRetry>,
    sent_order: &mut VecDeque<(CaptureSource, u64)>,
    error_sequence: Option<u64>,
    now: Instant,
) -> Option<BackpressureRetryNotice> {
    let is_retryable = |(source, sequence_number): (CaptureSource, u64)| {
        pending
            .get(&source)
            .and_then(|chunks| chunks.get(&sequence_number))
            .is_some_and(|chunk| !chunk.acknowledged)
    };
    let target = error_sequence
        .and_then(|error_sequence| {
            sent_order
                .iter()
                .copied()
                .find(|(source, sequence_number)| {
                    *sequence_number == error_sequence && is_retryable((*source, *sequence_number))
                })
                .or_else(|| {
                    pending.iter().find_map(|(&source, chunks)| {
                        chunks
                            .get(&error_sequence)
                            .filter(|chunk| !chunk.acknowledged)
                            .map(|_| (source, error_sequence))
                    })
                })
        })
        .or_else(|| {
            sent_order
                .iter()
                .copied()
                .find(|target| is_retryable(*target))
        });
    let Some((source, sequence_number)) = target else {
        return None;
    };

    let remove_source = {
        let pending_for_source = pending.get_mut(&source).expect("retry target exists");
        pending_for_source.remove(&sequence_number);
        pending_for_source.is_empty()
    };
    if remove_source {
        pending.remove(&source);
    }
    sent_order.retain(|entry| *entry != (source, sequence_number));
    sequence.insert(source, sequence_number);

    let attempts = retries
        .get(&source)
        .map_or(0, |retry| retry.attempts)
        .saturating_add(1);
    retries.insert(
        source,
        BackpressureRetry {
            attempts,
            retry_at: now + backpressure_delay(attempts),
        },
    );
    Some(BackpressureRetryNotice {
        source,
        sequence: sequence_number,
        attempts,
        retry_after_ms: backpressure_delay(attempts).as_millis() as u64,
    })
}

fn backend_event_channel(event: &BackendEvent) -> Option<&'static str> {
    match event {
        BackendEvent::Status { .. } => Some(MEETING_STATUS_EVENT),
        BackendEvent::SourceStatus { .. } => Some(SOURCE_STATUS_EVENT),
        BackendEvent::Transcript { .. } => Some(TRANSCRIPT_EVENT),
        BackendEvent::Question { .. } => Some(QUESTION_EVENT),
        BackendEvent::Answer { .. } => Some(ANSWER_EVENT),
        BackendEvent::Degraded { .. } => Some(DEGRADED_EVENT),
        BackendEvent::Ack { .. } | BackendEvent::Error { .. } => None,
    }
}

fn default_true() -> bool {
    true
}

fn default_system_source() -> CaptureSource {
    CaptureSource::System
}

fn emit_backend_event(app: &AppHandle, event: BackendEvent) {
    // Keep the aggregate channel for typed native consumers, while also exposing
    // the per-event channels used by the frontend bridge.  In particular, only
    // the parsed event is emitted; binary PCM is never an IPC payload.
    let _ = app.emit(BACKEND_EVENT, event.clone());
    if let Some(channel) = backend_event_channel(&event) {
        let _ = app.emit(channel, event);
    }
}

fn command_pending(receiver: &Receiver<WorkerCommand>) -> bool {
    matches!(
        receiver.try_recv(),
        Ok(WorkerCommand::Stop | WorkerCommand::Shutdown) | Err(mpsc::TryRecvError::Disconnected)
    )
}

fn begin_stop(
    app: &AppHandle,
    capture: &Arc<Mutex<CaptureManager>>,
    stop_requested: &mut bool,
    stop_deadline: &mut Option<Instant>,
) {
    capture.lock().shutdown(app);
    *stop_requested = true;
    *stop_deadline = Some(Instant::now() + STOP_AUDIO_DRAIN_TIMEOUT);
}

fn set_phase(
    app: &AppHandle,
    status: &Arc<Mutex<TransportStatus>>,
    phase: TransportPhase,
    attempts: u32,
    error: Option<String>,
) {
    let mut value = status.lock();
    value.phase = phase;
    value.reconnect_attempts = attempts;
    value.error = error;
    drop(value);
    emit_status(app, status);
}

fn emit_status(app: &AppHandle, status: &Arc<Mutex<TransportStatus>>) {
    let _ = app.emit(TRANSPORT_STATUS_EVENT, status.lock().clone());
}

fn finish(
    app: &AppHandle,
    capture: &Arc<Mutex<CaptureManager>>,
    status: &Arc<Mutex<TransportStatus>>,
    failed: bool,
    error: Option<String>,
) {
    capture.lock().shutdown(app);
    let mut status_value = status.lock();
    status_value.phase = if failed {
        TransportPhase::Failed
    } else {
        TransportPhase::Stopped
    };
    status_value.error = error;
    let _ = app.emit(TRANSPORT_STATUS_EVENT, status_value.clone());
}

#[derive(Debug, thiserror::Error)]
enum WorkerError {
    #[error("websocket connection failed: {0}")]
    Connection(String),
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read;
    use std::net::TcpListener;

    #[test]
    fn constructs_canonical_backend_path_and_origin_policy() {
        let request = TransportRequest {
            meeting_id: "meeting-1".into(),
            backend_url: "http://127.0.0.1:8000".into(),
            stream_ticket: "A".repeat(43),
        };
        validate_request(&request).unwrap();
        let url = Url::parse(&request.backend_url).unwrap();
        assert_eq!(url.host_str(), Some("127.0.0.1"));
        assert_eq!(ORIGIN, "tauri://localhost");
    }

    #[test]
    fn rejects_non_local_backend() {
        let request = TransportRequest {
            meeting_id: "id".into(),
            backend_url: "https://example.test".into(),
            stream_ticket: "A".repeat(43),
        };
        assert!(validate_request(&request).is_err());
    }

    #[test]
    fn transport_request_matches_frontend_camel_case() {
        let request: TransportRequest = serde_json::from_str(
            r#"{"meetingId":"meeting-1","backendUrl":"http://localhost:8000","streamTicket":"A12345678901234567890123456789012345678901"}"#,
        )
        .unwrap();
        assert_eq!(request.meeting_id, "meeting-1");
        assert_eq!(request.backend_url, "http://localhost:8000");
        assert_eq!(
            request.stream_ticket,
            "A12345678901234567890123456789012345678901"
        );
    }

    #[test]
    fn native_handshake_sends_the_meeting_stream_ticket() {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = thread::spawn(move || {
            let (mut socket, _) = listener.accept().unwrap();
            socket.set_read_timeout(Some(HANDSHAKE_TIMEOUT)).unwrap();
            let mut request = Vec::new();
            let mut buffer = [0_u8; 1024];
            loop {
                let count = socket.read(&mut buffer).unwrap();
                request.extend_from_slice(&buffer[..count]);
                if request.windows(4).any(|window| window == b"\r\n\r\n") {
                    break;
                }
            }
            String::from_utf8(request).unwrap()
        });
        let stream_ticket = "A12345678901234567890123456789012345678901";
        let request = TransportRequest {
            meeting_id: "meeting-1".into(),
            backend_url: format!("http://127.0.0.1:{port}"),
            stream_ticket: stream_ticket.into(),
        };

        assert!(connect_socket(&request).is_err());
        let handshake = server.join().unwrap();
        assert!(handshake.to_ascii_lowercase().contains(&format!(
            "x-meeting-stream-ticket: {}",
            stream_ticket.to_ascii_lowercase()
        )));
    }

    #[test]
    fn strict_inference_events_are_forwardable_and_non_terminal() {
        let events = [
            (
                r#"{"type":"transcript","meeting_id":"meeting-1","segment_id":"segment-1","source":"system","text":"Hello","start_ms":0,"end_ms":100,"final":true}"#,
                Some(TRANSCRIPT_EVENT),
            ),
            (
                r#"{"type":"question","meeting_id":"meeting-1","question_id":"question-1","source":"system","text":"What next?"}"#,
                Some(QUESTION_EVENT),
            ),
            (
                r#"{"type":"answer","meeting_id":"meeting-1","question_id":"question-1","answer":"Continue locally.","citations":[]}"#,
                Some(ANSWER_EVENT),
            ),
            (
                r#"{"type":"degraded","meeting_id":"meeting-1","component":"asr","message":"ASR unavailable."}"#,
                Some(DEGRADED_EVENT),
            ),
        ];

        for (payload, channel) in events {
            let event = serde_json::from_str::<BackendEvent>(payload).unwrap();
            assert_eq!(backend_event_channel(&event), channel);
            assert_eq!(backend_event_terminal(&event), None);
        }
    }

    #[test]
    fn reconnect_resets_sequences_for_a_new_backend_session() {
        let mut sequence =
            HashMap::from([(CaptureSource::System, 9), (CaptureSource::Microphone, 3)]);
        let pending = HashMap::from([(
            CaptureSource::System,
            BTreeMap::from([(
                7,
                PendingChunk {
                    frame_count: 1,
                    acknowledged: false,
                },
            )]),
        )]);

        reset_sequences_for_reconnect(&mut sequence, &pending);

        assert_eq!(sequence[&CaptureSource::System], 0);
        assert_eq!(sequence[&CaptureSource::Microphone], 0);
    }

    #[test]
    fn backpressure_retries_the_same_chunk_without_advancing_sequence() {
        assert_eq!(MAX_IN_FLIGHT_PER_SOURCE, 1);
        let source = CaptureSource::System;
        let mut sequence = HashMap::from([(source, 5)]);
        let mut pending = HashMap::from([(
            source,
            BTreeMap::from([(
                4,
                PendingChunk {
                    frame_count: 960,
                    acknowledged: false,
                },
            )]),
        )]);
        let mut retries = HashMap::new();
        let mut sent_order = VecDeque::from([(source, 4)]);
        let now = Instant::now();

        let notice = schedule_backpressure_retry(
            &mut pending,
            &mut sequence,
            &mut retries,
            &mut sent_order,
            None,
            now,
        )
        .expect("pending chunk should be scheduled for retry");
        assert_eq!(sequence[&source], 4);
        assert_eq!(notice.source, source);
        assert_eq!(notice.sequence, 4);
        assert_eq!(notice.attempts, 1);
        assert!(pending.get(&source).is_none());
        assert!(sent_order.is_empty());
        assert_eq!(retries[&source].attempts, 1);
        assert!(retries[&source].retry_at >= now + Duration::from_millis(25));

        assert_eq!(backpressure_delay(100), Duration::from_millis(500));
    }

    #[test]
    fn reconnect_budget_counts_immediate_connect_then_close_cycles() {
        assert_eq!(reconnect_attempts(0, Duration::from_millis(1)), 1);
        assert_eq!(reconnect_attempts(1, Duration::from_millis(1)), 2);
        assert_eq!(reconnect_attempts(5, Duration::from_millis(1)), 6);
        assert_eq!(reconnect_attempts(5, RECONNECT_STABILITY_WINDOW), 1);
    }

    #[test]
    fn active_session_conflict_is_retryable_not_terminal() {
        let event = serde_json::from_str::<BackendEvent>(
            r#"{"type":"error","code":"ACTIVE_AUDIO_SESSION","message":"Another stream is active."}"#,
        )
        .unwrap();
        assert!(backend_event_retryable(&event));
        assert_eq!(backend_event_terminal(&event), None);
    }

    #[test]
    fn backpressure_event_has_typed_frontend_payload() {
        let event = BackpressureEvent::Processor {
            meeting_id: "meeting-1".into(),
            source: Some(CaptureSource::System),
            sequence: Some(3),
            attempts: 2,
            retry_after_ms: 50,
            message: "retrying".into(),
        };
        let payload = serde_json::to_value(event).unwrap();
        assert_eq!(payload["type"], "processor");
        assert_eq!(payload["meetingId"], "meeting-1");
        assert_eq!(payload["retryAfterMs"], 50);
    }

    #[test]
    fn stop_audio_timeout_is_bounded_by_the_transport_drain_budget() {
        assert_eq!(STOP_AUDIO_DRAIN_TIMEOUT, Duration::from_secs(2));
        assert!(STOP_AUDIO_DRAIN_TIMEOUT < Duration::from_secs(5));
    }

    #[test]
    fn unresponsive_local_peer_cannot_block_websocket_handshake() {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = thread::spawn(move || {
            let (_stream, _) = listener.accept().unwrap();
            thread::sleep(HANDSHAKE_TIMEOUT + Duration::from_millis(50));
        });
        let request = TransportRequest {
            meeting_id: "meeting-1".into(),
            backend_url: format!("http://127.0.0.1:{port}"),
            stream_ticket: "A".repeat(43),
        };
        let started = Instant::now();

        let result = connect_socket(&request);

        assert!(result.is_err());
        assert!(started.elapsed() < HANDSHAKE_TIMEOUT + Duration::from_secs(1));
        server.join().unwrap();
    }
}
