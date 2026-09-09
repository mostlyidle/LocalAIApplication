use std::{
    collections::HashMap,
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc::{sync_channel, SyncSender},
        Arc,
    },
    thread,
    time::Duration,
};

use cpal::{
    traits::{DeviceTrait, HostTrait, StreamTrait},
    Device, Stream, SupportedStreamConfig,
};
use parking_lot::Mutex;
use windows::Win32::Media::Audio::{
    eConsole, eRender, IAudioCaptureClient, IAudioClient, IMMDeviceEnumerator, MMDeviceEnumerator,
    AUDCLNT_SHAREMODE_SHARED, AUDCLNT_STREAMFLAGS_LOOPBACK,
};
use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, CoTaskMemFree, CoUninitialize, CLSCTX_ALL,
    COINIT_MULTITHREADED,
};

use super::NativeCapture;
use crate::{
    error::CaptureError,
    model::{
        AudioDevice, Capabilities, Capability, CaptureSource, Permission, PermissionKind,
        PermissionState, PermissionStatus, SourceStatus,
    },
    pcm::PcmRing,
};

enum ActiveCapture {
    Microphone(Stream),
    System {
        stop: Arc<AtomicBool>,
        thread: thread::JoinHandle<()>,
    },
}

pub struct WindowsCapture {
    active: Mutex<HashMap<CaptureSource, ActiveCapture>>,
}

impl WindowsCapture {
    pub fn new() -> Self {
        Self {
            active: Mutex::new(HashMap::new()),
        }
    }
}

impl Drop for WindowsCapture {
    fn drop(&mut self) {
        for (_, active) in self.active.get_mut().drain() {
            match active {
                ActiveCapture::Microphone(stream) => drop(stream),
                ActiveCapture::System { stop, thread } => {
                    stop.store(true, Ordering::Release);
                    let _ = thread.join();
                }
            }
        }
    }
}

fn host() -> cpal::Host {
    cpal::default_host()
}

fn device_name(device: &Device) -> String {
    device
        .name()
        .unwrap_or_else(|_| "Unnamed audio device".into())
}

impl NativeCapture for WindowsCapture {
    fn start(
        &self,
        source: CaptureSource,
        requested_id: Option<&str>,
        queue: Arc<Mutex<PcmRing>>,
    ) -> Result<(), CaptureError> {
        if source == CaptureSource::System {
            let stop = Arc::new(AtomicBool::new(false));
            let thread_stop = Arc::clone(&stop);
            let failure_queue = Arc::clone(&queue);
            let (ready_tx, ready_rx) = sync_channel(1);
            let thread = thread::Builder::new()
                .name("localai-wasapi-loopback".into())
                .spawn(move || {
                    if let Err(error) = wasapi_loopback(queue, thread_stop, ready_tx) {
                        failure_queue.lock().fail(error.to_string());
                    }
                })
                .map_err(|error| CaptureError::Native(error.to_string()))?;
            let thread = match ready_rx.recv_timeout(Duration::from_secs(5)) {
                Ok(Ok(())) => thread,
                Ok(Err(error)) => {
                    stop.store(true, Ordering::Release);
                    let _ = thread.join();
                    return Err(CaptureError::Native(error));
                }
                Err(_) => {
                    stop.store(true, Ordering::Release);
                    let _ = thread.join();
                    return Err(CaptureError::Native(
                        "WASAPI loopback did not become ready".into(),
                    ));
                }
            };
            self.active
                .lock()
                .insert(source, ActiveCapture::System { stop, thread });
            return Ok(());
        }

        let host = host();
        let device = if let Some(id) = requested_id {
            host.input_devices()
                .map_err(|error| CaptureError::Device(error.to_string()))?
                .find(|candidate| device_name(candidate) == id)
                .ok_or_else(|| CaptureError::Device(format!("microphone '{id}' was not found")))?
        } else {
            host.default_input_device()
                .ok_or_else(|| CaptureError::Device("no default microphone is available".into()))?
        };
        let supported = device
            .default_input_config()
            .map_err(|error| CaptureError::Device(error.to_string()))?;
        queue.lock().set_format(
            supported.sample_rate().0,
            supported.channels(),
            sample_encoding(supported.sample_format()),
        );
        let stream = build_microphone_stream(&device, &supported, queue)?;
        stream
            .play()
            .map_err(|error| CaptureError::Native(error.to_string()))?;
        self.active
            .lock()
            .insert(source, ActiveCapture::Microphone(stream));
        Ok(())
    }

    fn stop(&self, source: CaptureSource) -> Result<(), CaptureError> {
        let Some(active) = self.active.lock().remove(&source) else {
            return Err(CaptureError::NotRunning(source.as_str().into()));
        };
        match active {
            ActiveCapture::Microphone(stream) => drop(stream),
            ActiveCapture::System { stop, thread } => {
                stop.store(true, Ordering::Release);
                let _ = thread.join();
            }
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
        let host = host();
        let mut devices = Vec::new();
        if let Some(output) = host.default_output_device() {
            devices.push(AudioDevice {
                id: "system-mix".into(),
                name: format!("System Audio Mix ({})", device_name(&output)),
                source: CaptureSource::System,
                is_default: true,
                channels: 2,
                sample_rate: 48_000,
                native_encoding: "native (reported after start)".into(),
                buffer_encoding: "f32le".into(),
            });
        }
        for device in host
            .input_devices()
            .map_err(|error| CaptureError::Device(error.to_string()))?
        {
            let config = device.default_input_config().ok();
            devices.push(AudioDevice {
                id: device_name(&device),
                name: device_name(&device),
                source: CaptureSource::Microphone,
                is_default: false,
                channels: config.as_ref().map_or(1, |value| value.channels()),
                sample_rate: config
                    .as_ref()
                    .map_or(48_000, |value| value.sample_rate().0),
                native_encoding: "native".into(),
                buffer_encoding: "f32le".into(),
            });
        }
        Ok(devices)
    }
}

fn build_microphone_stream(
    device: &Device,
    config: &SupportedStreamConfig,
    queue: Arc<Mutex<PcmRing>>,
) -> Result<Stream, CaptureError> {
    let stream_config = config.config();
    let channels = config.channels();
    let error_queue = Arc::clone(&queue);
    let error_callback = move |error| {
        error_queue
            .lock()
            .fail(format!("microphone stream error: {error}"))
    };
    let stream = match config.sample_format() {
        cpal::SampleFormat::F32 => device.build_input_stream(
            &stream_config,
            move |data: &[f32], _| push(queue.clone(), data, channels),
            error_callback,
            None,
        ),
        cpal::SampleFormat::I16 => device.build_input_stream(
            &stream_config,
            move |data: &[i16], _| {
                let converted: Vec<f32> = data
                    .iter()
                    .map(|sample| f32::from(*sample) / 32_768.0)
                    .collect();
                push(queue.clone(), &converted, channels);
            },
            error_callback,
            None,
        ),
        cpal::SampleFormat::U16 => device.build_input_stream(
            &stream_config,
            move |data: &[u16], _| {
                let converted: Vec<f32> = data
                    .iter()
                    .map(|sample| (f32::from(*sample) - 32_768.0) / 32_768.0)
                    .collect();
                push(queue.clone(), &converted, channels);
            },
            error_callback,
            None,
        ),
        format => {
            return Err(CaptureError::Device(format!(
                "unsupported microphone format: {format:?}"
            )))
        }
    };
    stream.map_err(|error| CaptureError::Device(error.to_string()))
}

fn push(queue: Arc<Mutex<PcmRing>>, samples: &[f32], channels: u16) {
    let mut queue = queue.lock();
    queue.set_channels(channels);
    queue.push_interleaved(samples);
}

fn sample_encoding(format: cpal::SampleFormat) -> &'static str {
    match format {
        cpal::SampleFormat::F32 => "f32le",
        cpal::SampleFormat::I16 => "s16le",
        cpal::SampleFormat::U16 => "u16le",
        _ => "native",
    }
}

/// Captures the render endpoint's post-mix stream through the WASAPI loopback flag.
/// This deliberately does not use a browser/Web Audio fallback.
fn wasapi_loopback(
    queue: Arc<Mutex<PcmRing>>,
    stop: Arc<AtomicBool>,
    ready: SyncSender<Result<(), String>>,
) -> Result<(), CaptureError> {
    unsafe {
        if let Err(error) = CoInitializeEx(None, COINIT_MULTITHREADED) {
            let message = error.to_string();
            let _ = ready.send(Err(message.clone()));
            return Err(CaptureError::Native(message));
        }
        let result = wasapi_loopback_inner(queue, stop, &ready);
        CoUninitialize();
        if let Err(error) = &result {
            let _ = ready.send(Err(error.to_string()));
        }
        result
    }
}

unsafe fn wasapi_loopback_inner(
    queue: Arc<Mutex<PcmRing>>,
    stop: Arc<AtomicBool>,
    ready: &SyncSender<Result<(), String>>,
) -> Result<(), CaptureError> {
    let enumerator: IMMDeviceEnumerator =
        CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL)
            .map_err(|error| CaptureError::Native(error.to_string()))?;
    let device = enumerator
        .GetDefaultAudioEndpoint(eRender, eConsole)
        .map_err(|error| CaptureError::Device(error.to_string()))?;
    let client: IAudioClient = device
        .Activate(CLSCTX_ALL, None)
        .map_err(|error| CaptureError::Native(error.to_string()))?;
    let format = client
        .GetMixFormat()
        .map_err(|error| CaptureError::Native(error.to_string()))?;
    let parsed = match parse_wave_format(format) {
        Ok(parsed) => parsed,
        Err(error) => {
            CoTaskMemFree(Some(format.cast()));
            return Err(error);
        }
    };
    let initialized = client.Initialize(
        AUDCLNT_SHAREMODE_SHARED,
        AUDCLNT_STREAMFLAGS_LOOPBACK,
        10_000_000,
        0,
        format,
        None,
    );
    CoTaskMemFree(Some(format.cast()));
    initialized.map_err(|error| CaptureError::Native(error.to_string()))?;
    let channels = parsed.channels;
    queue.lock().set_format(
        parsed.sample_rate_hz,
        parsed.channels,
        parsed.encoding.as_str(),
    );
    let capture: IAudioCaptureClient = client
        .GetService::<IAudioCaptureClient>()
        .map_err(|error| CaptureError::Native(error.to_string()))?;
    client
        .Start()
        .map_err(|error| CaptureError::Native(error.to_string()))?;
    let _ = ready.send(Ok(()));
    while !stop.load(Ordering::Acquire) {
        let mut data = std::ptr::null_mut();
        let mut frames = 0;
        let mut flags = 0;
        if capture
            .GetBuffer(&mut data, &mut frames, &mut flags, None, None)
            .is_ok()
            && frames > 0
        {
            let count = frames as usize * channels as usize;
            let mut queue = queue.lock();
            queue.set_channels(channels);
            if data.is_null() || flags & 0x2 != 0 {
                queue.push_interleaved(&vec![0.0; count]);
            } else {
                match parsed.encoding.as_str() {
                    "f32le" => {
                        let samples = std::slice::from_raw_parts(data as *const f32, count);
                        queue.push_interleaved(samples);
                    }
                    "s16le" => {
                        let samples = std::slice::from_raw_parts(data as *const i16, count);
                        let converted: Vec<f32> = samples
                            .iter()
                            .map(|sample| f32::from(*sample) / 32_768.0)
                            .collect();
                        queue.push_interleaved(&converted);
                    }
                    "s32le" => {
                        let samples = std::slice::from_raw_parts(data as *const i32, count);
                        let converted: Vec<f32> = samples
                            .iter()
                            .map(|sample| *sample as f32 / 2_147_483_648.0)
                            .collect();
                        queue.push_interleaved(&converted);
                    }
                    "s24le" => {
                        let bytes = std::slice::from_raw_parts(data as *const u8, count * 3);
                        let converted: Vec<f32> = bytes
                            .chunks_exact(3)
                            .map(|sample| {
                                let sign = if sample[2] & 0x80 != 0 { 0xff } else { 0 };
                                let value =
                                    i32::from_le_bytes([sample[0], sample[1], sample[2], sign]);
                                value as f32 / 8_388_608.0
                            })
                            .collect();
                        queue.push_interleaved(&converted);
                    }
                    "u8le" => {
                        let samples = std::slice::from_raw_parts(data as *const u8, count);
                        let converted: Vec<f32> = samples
                            .iter()
                            .map(|sample| (f32::from(*sample) - 128.0) / 128.0)
                            .collect();
                        queue.push_interleaved(&converted);
                    }
                    _ => queue.fail("WASAPI returned an unsupported PCM encoding"),
                }
            }
            capture.ReleaseBuffer(frames).ok();
        }
        thread::sleep(Duration::from_millis(10));
    }
    client.Stop().ok();
    Ok(())
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct WasapiFormat {
    sample_rate_hz: u32,
    channels: u16,
    encoding: String,
}

const WAVE_FORMAT_PCM: u16 = 0x0001;
const WAVE_FORMAT_IEEE_FLOAT: u16 = 0x0003;
const WAVE_FORMAT_EXTENSIBLE: u16 = 0xfffe;

/// Copies and validates the OS-owned WAVEFORMATEX/WAVEFORMATEXTENSIBLE allocation before use.
unsafe fn parse_wave_format(
    raw: *const windows::Win32::Media::Audio::WAVEFORMATEX,
) -> Result<WasapiFormat, CaptureError> {
    if raw.is_null() {
        return Err(CaptureError::Native(
            "WASAPI returned a null mix format".into(),
        ));
    }
    let base = std::slice::from_raw_parts(raw.cast::<u8>(), 18);
    let tag = u16::from_le_bytes([base[0], base[1]]);
    let channels = u16::from_le_bytes([base[2], base[3]]);
    let rate = u32::from_le_bytes([base[4], base[5], base[6], base[7]]);
    let bits = u16::from_le_bytes([base[14], base[15]]);
    let extra = u16::from_le_bytes([base[16], base[17]]) as usize;
    if channels == 0 || rate == 0 {
        return Err(CaptureError::Native(
            "WASAPI returned an invalid audio format".into(),
        ));
    }
    let encoding = match tag {
        WAVE_FORMAT_PCM if bits == 8 => "u8le",
        WAVE_FORMAT_PCM if bits == 16 => "s16le",
        WAVE_FORMAT_PCM if bits == 24 => "s24le",
        WAVE_FORMAT_PCM if bits == 32 => "s32le",
        WAVE_FORMAT_IEEE_FLOAT if bits == 32 => "f32le",
        WAVE_FORMAT_EXTENSIBLE if extra >= 22 => {
            let bytes = std::slice::from_raw_parts(raw.cast::<u8>(), 18 + extra);
            let subtype = u32::from_le_bytes([bytes[24], bytes[25], bytes[26], bytes[27]]);
            let subtype_tag = u16::try_from(subtype).unwrap_or(0);
            let guid_tail = &bytes[28..40];
            let valid_guid = guid_tail == [0, 0, 0x10, 0, 0x80, 0, 0, 0xaa, 0, 0x38, 0x9b, 0x71];
            if !valid_guid {
                return Err(CaptureError::Native(
                    "unsupported WAVE_FORMAT_EXTENSIBLE GUID".into(),
                ));
            }
            match (subtype_tag, bits) {
                (1, 8) => "u8le",
                (1, 16) => "s16le",
                (1, 24) => "s24le",
                (1, 32) => "s32le",
                (3, 32) => "f32le",
                _ => {
                    return Err(CaptureError::Native(
                        "unsupported WAVE_FORMAT_EXTENSIBLE subtype".into(),
                    ))
                }
            }
        }
        _ => return Err(CaptureError::Native("unsupported WASAPI mix format".into())),
    };
    Ok(WasapiFormat {
        sample_rate_hz: rate,
        channels,
        encoding: encoding.into(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_extensible_float_format() {
        let mut bytes = vec![0u8; 40];
        bytes[0..2].copy_from_slice(&WAVE_FORMAT_EXTENSIBLE.to_le_bytes());
        bytes[2..4].copy_from_slice(&2u16.to_le_bytes());
        bytes[4..8].copy_from_slice(&48_000u32.to_le_bytes());
        bytes[14..16].copy_from_slice(&32u16.to_le_bytes());
        bytes[16..18].copy_from_slice(&22u16.to_le_bytes());
        bytes[24..28].copy_from_slice(&3u32.to_le_bytes());
        bytes[28..40].copy_from_slice(&[0, 0, 0x10, 0, 0x80, 0, 0, 0xaa, 0, 0x38, 0x9b, 0x71]);
        let parsed = unsafe { parse_wave_format(bytes.as_ptr().cast()) }.unwrap();
        assert_eq!(
            parsed,
            WasapiFormat {
                sample_rate_hz: 48_000,
                channels: 2,
                encoding: "f32le".into()
            }
        );
    }

    #[test]
    fn parses_pcm_16_format() {
        let mut bytes = vec![0u8; 18];
        bytes[0..2].copy_from_slice(&WAVE_FORMAT_PCM.to_le_bytes());
        bytes[2..4].copy_from_slice(&1u16.to_le_bytes());
        bytes[4..8].copy_from_slice(&44_100u32.to_le_bytes());
        bytes[14..16].copy_from_slice(&16u16.to_le_bytes());
        let parsed = unsafe { parse_wave_format(bytes.as_ptr().cast()) }.unwrap();
        assert_eq!(parsed.encoding, "s16le");
        assert_eq!(parsed.sample_rate_hz, 44_100);
    }
}

pub fn capabilities() -> Capabilities {
    Capabilities { platform: "windows".into(), system_mix: true, per_process_system_audio: false, sources: vec![
        Capability { source: CaptureSource::System, available: true, native: true, limitation: Some("WASAPI loopback captures the render endpoint system mix; per-process capture is not enabled in Phase 1.".into()) },
        Capability { source: CaptureSource::Microphone, available: true, native: true, limitation: Some("Capture uses the selected Windows input endpoint through CPAL.".into()) },
    ] }
}

pub fn permissions() -> PermissionStatus {
    PermissionStatus {
        screen_recording: Permission { state: PermissionState::NotApplicable, can_request: false, settings_url: String::new() },
        microphone: Permission { state: PermissionState::Unknown, can_request: false, settings_url: "ms-settings:privacy-microphone".into() },
        notes: vec!["Windows microphone privacy settings can block an endpoint; WASAPI reports the resulting native error.".into()],
    }
}

pub fn request_permissions(_: PermissionKind) -> Result<PermissionStatus, CaptureError> {
    Ok(permissions())
}

pub fn open_permission_settings(_: PermissionKind) -> Result<(), CaptureError> {
    std::process::Command::new("explorer.exe")
        .arg("ms-settings:privacy-microphone")
        .spawn()
        .map(|_| ())
        .map_err(|error| {
            CaptureError::Native(format!(
                "could not open Windows microphone settings: {error}"
            ))
        })
}
