use std::{
    collections::VecDeque,
    sync::atomic::{AtomicBool, Ordering},
};

use serde::Serialize;

use crate::model::{AudioFormat, MAX_BUFFERED_FRAMES};

/// A bounded native-only PCM queue. PCM never crosses the Tauri event boundary.
pub struct PcmRing {
    samples: VecDeque<f32>,
    channels: usize,
    active: AtomicBool,
    dropped_frames: u64,
    format: Option<AudioFormat>,
    error: Option<String>,
}

impl PcmRing {
    pub fn new(channels: u16) -> Self {
        Self {
            samples: VecDeque::new(),
            channels: usize::from(channels.max(1)),
            active: AtomicBool::new(true),
            dropped_frames: 0,
            format: None,
            error: None,
        }
    }

    pub fn push_interleaved(&mut self, samples: &[f32]) {
        if !self.is_active() {
            return;
        }
        self.samples.extend(samples.iter().copied());
        let capacity = MAX_BUFFERED_FRAMES.saturating_mul(self.channels);
        let before = self.samples.len();
        while self.samples.len() > capacity {
            self.samples.pop_front();
        }
        self.dropped_frames += ((before - self.samples.len()) / self.channels) as u64;
    }

    pub fn set_channels(&mut self, channels: u16) {
        if self.samples.is_empty() {
            self.channels = usize::from(channels.max(1));
        }
    }

    pub fn set_format(&mut self, sample_rate_hz: u32, channels: u16, encoding: impl Into<String>) {
        self.set_channels(channels);
        self.format = Some(AudioFormat {
            sample_rate_hz,
            channels,
            native_encoding: encoding.into(),
            buffer_encoding: "f32le".into(),
        });
    }

    pub fn frames(&self) -> usize {
        self.samples.len() / self.channels
    }

    pub fn meter_samples(&self) -> Vec<f32> {
        let count = self.samples.len().min(2_048);
        self.samples
            .iter()
            .skip(self.samples.len() - count)
            .copied()
            .collect()
    }

    pub fn drain(&mut self, max_frames: usize) -> Vec<f32> {
        let count = max_frames.min(self.frames()).saturating_mul(self.channels);
        self.samples.drain(..count).collect()
    }

    pub fn peek(&self, max_frames: usize) -> Vec<f32> {
        self.peek_from(0, max_frames)
    }

    pub fn peek_from(&self, offset_frames: usize, max_frames: usize) -> Vec<f32> {
        let start = offset_frames
            .min(self.frames())
            .saturating_mul(self.channels);
        let count = max_frames
            .min(self.frames().saturating_sub(offset_frames))
            .saturating_mul(self.channels);
        self.samples
            .iter()
            .skip(start)
            .take(count)
            .copied()
            .collect()
    }

    pub fn dropped_frames(&self) -> u64 {
        self.dropped_frames
    }

    pub fn stats(&self) -> BufferStats {
        BufferStats {
            frames_buffered: self.frames(),
            dropped_frames: self.dropped_frames,
        }
    }

    pub fn format(&self) -> Option<AudioFormat> {
        self.format.clone()
    }

    pub fn error(&self) -> Option<String> {
        self.error.clone()
    }

    pub fn is_active(&self) -> bool {
        self.active.load(Ordering::Acquire)
    }

    pub fn deactivate(&self) {
        self.active.store(false, Ordering::Release);
    }

    pub fn fail(&mut self, error: impl Into<String>) {
        self.error = Some(error.into());
        self.deactivate();
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct BufferStats {
    pub frames_buffered: usize,
    pub dropped_frames: u64,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn buffer_drains_and_counts_dropped_frames() {
        let mut buffer = PcmRing::new(2);
        let samples = vec![0.25; (MAX_BUFFERED_FRAMES + 4) * 2];
        buffer.push_interleaved(&samples);
        assert_eq!(buffer.frames(), MAX_BUFFERED_FRAMES);
        assert_eq!(buffer.dropped_frames(), 4);
        assert_eq!(buffer.drain(3).len(), 6);
        assert_eq!(buffer.frames(), MAX_BUFFERED_FRAMES - 3);
    }

    #[test]
    fn failed_buffer_rejects_new_pcm() {
        let mut buffer = PcmRing::new(1);
        buffer.fail("native stream ended");
        buffer.push_interleaved(&[1.0]);
        assert_eq!(buffer.frames(), 0);
        assert_eq!(buffer.error().as_deref(), Some("native stream ended"));
    }

    #[test]
    fn deactivating_capture_keeps_buffered_pcm_available_for_transport_drain() {
        let mut buffer = PcmRing::new(1);
        buffer.push_interleaved(&[0.25, -0.25]);
        buffer.deactivate();

        assert!(!buffer.is_active());
        assert_eq!(buffer.frames(), 2);
        assert_eq!(buffer.drain(2), vec![0.25, -0.25]);
    }
}

pub fn levels(samples: &[f32]) -> (f32, f32) {
    if samples.is_empty() {
        return (0.0, 0.0);
    }
    let mut sum = 0.0_f64;
    let mut peak = 0.0_f32;
    for &sample in samples {
        let value = sample.abs();
        sum += f64::from(value * value);
        peak = peak.max(value);
    }
    ((sum / samples.len() as f64).sqrt() as f32, peak.min(1.0))
}
