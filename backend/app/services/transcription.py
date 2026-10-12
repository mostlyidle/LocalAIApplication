"""Offline local transcription boundary for meeting audio."""

from __future__ import annotations

import asyncio
import platform
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import structlog

from app.config import settings

if TYPE_CHECKING:
    from app.models.enums import AudioSource

logger = structlog.get_logger(__name__)

ASR_READINESS_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class TranscriptionChunk:
    """One final transcript result from an ASR engine."""

    text: str
    start_ms: int = 0
    end_ms: int = 0


class TranscriptionEngine(ABC):
    """Provider-neutral offline transcription interface."""

    async def load(self) -> None:
        """Prepare local resources; artifact-free engines need no setup."""
        return None

    @abstractmethod
    async def transcribe(
        self,
        pcm: bytes,
        *,
        sample_rate_hz: int,
        channels: int,
        source: AudioSource,
        final: bool = False,
    ) -> list[TranscriptionChunk]:
        """Transcribe a bounded PCM window."""

    async def close(self) -> None:
        """Release provider resources."""
        return None


class FakeTranscriptionEngine(TranscriptionEngine):
    """Deterministic engine for service and WebSocket tests."""

    def __init__(self, results: list[TranscriptionChunk] | None = None) -> None:
        self.results = list(results or [])
        self.calls: list[dict[str, Any]] = []

    async def transcribe(
        self,
        pcm: bytes,
        *,
        sample_rate_hz: int,
        channels: int,
        source: AudioSource,
        final: bool = False,
    ) -> list[TranscriptionChunk]:
        """Record bounded input metadata and return deterministic results."""
        self.calls.append(
            {
                "pcm_bytes": len(pcm),
                "sample_rate_hz": sample_rate_hz,
                "channels": channels,
                "source": source,
                "final": final,
            }
        )
        return list(self.results)


class FasterWhisperTranscriptionEngine(TranscriptionEngine):
    """CPU/int8 faster-whisper engine loaded only from a local model folder."""

    def __init__(self, model_dir: str | Path | None = None) -> None:
        configured = model_dir if model_dir is not None else settings.asr_model_dir
        self.model_dir = _require_model_dir(configured)
        if settings.asr_model_name != "small.en":
            raise ValueError("ASR model must be configured as small.en")
        self._model: Any | None = None
        self._load_lock = asyncio.Lock()
        self._load_task: asyncio.Task[Any] | None = None

    async def load(self) -> None:
        """Load the local CTranslate2 model without network access."""
        if self._model is not None:
            return

        def _load() -> Any:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError("faster-whisper is not installed") from exc
            return WhisperModel(
                str(self.model_dir),
                device="cpu",
                compute_type="int8",
                local_files_only=True,
            )

        async with self._load_lock:
            if self._model is not None:
                return
            load_task = self._load_task
            if load_task is None:
                load_task = asyncio.create_task(asyncio.to_thread(_load))
                self._load_task = load_task

        try:
            model = await asyncio.shield(load_task)
        except BaseException:
            # A readiness timeout/cancellation must not discard a still-running
            # worker thread.  Keep the task so the next caller can await it.
            async with self._load_lock:
                if self._load_task is load_task and load_task.done():
                    self._load_task = None
            raise

        async with self._load_lock:
            if self._model is None:
                self._model = model
            if self._load_task is load_task:
                self._load_task = None

    async def transcribe(
        self,
        pcm: bytes,
        *,
        sample_rate_hz: int,
        channels: int,
        source: AudioSource,
        final: bool = False,
    ) -> list[TranscriptionChunk]:
        """Transcribe normalized signed-16 PCM with built-in VAD."""
        await self.load()
        audio = _pcm_to_float32(pcm, channels)
        audio = _resample_mono(audio, sample_rate_hz)

        def _transcribe() -> list[TranscriptionChunk]:
            segments, _info = self._model.transcribe(  # type: ignore[union-attr]
                audio,
                language="en",
                vad_filter=True,
            )
            return [
                TranscriptionChunk(
                    text=str(segment.text).strip(),
                    start_ms=int(float(segment.start) * 1_000),
                    end_ms=int(float(segment.end) * 1_000),
                )
                for segment in segments
                if str(segment.text).strip()
            ]

        return await asyncio.to_thread(_transcribe)


class MLXWhisperTranscriptionEngine(TranscriptionEngine):
    """Apple Silicon Whisper engine using explicitly provisioned local MLX weights."""

    # MLX Whisper's ModelHolder is shared across instances, including benchmark engines.
    _model_lock = threading.Lock()

    def __init__(self, model_dir: str | Path | None = None) -> None:
        if platform.system() != "Darwin" or platform.machine().lower() != "arm64":
            raise ValueError("MLX Whisper requires an Apple Silicon Mac")
        version = platform.mac_ver()[0]
        if not version or int(version.split(".")[0]) < 26:
            raise ValueError(
                "The locked MLX runtime requires macOS 26 or later; "
                "use faster-whisper on older macOS"
            )
        configured = model_dir if model_dir is not None else settings.asr_model_dir
        if configured is None:
            raise ValueError("ASR_MODEL_DIR must point to an absolute local MLX model directory")
        path = Path(configured).expanduser()
        if not path.is_absolute() or not path.is_dir():
            raise ValueError("ASR_MODEL_DIR must be an existing absolute local MLX directory")
        if not (path / "config.json").is_file() or not any(
            (path / name).is_file()
            for name in ("weights.safetensors", "weights.npz")
        ):
            raise ValueError(
                "MLX model directory must contain config.json and weights.safetensors or weights.npz"
            )
        self.model_dir = path.resolve()
        self._loaded = False
        self._load_task: asyncio.Task[None] | None = None

    async def load(self) -> None:
        """Load weights once; a readiness timeout must not start another GPU load."""
        if self._loaded:
            return
        if self._load_task is None:
            self._load_task = asyncio.create_task(asyncio.to_thread(self._load_model))
        # A failed native MLX import can leave partially initialized extension state.
        # Cache the failed task until restart rather than repeatedly initializing Metal.
        await asyncio.shield(self._load_task)

    def _load_model(self) -> None:
        with self._model_lock:
            try:
                import mlx.core as mx
                from mlx_whisper.transcribe import ModelHolder
            except ImportError as exc:
                raise RuntimeError("Install the MLX speech extra with uv sync --extra mlx") from exc
            # Checking files first prevents MLX's Hub fallback for a missing local path.
            if not self.model_dir.is_dir():
                raise ValueError("Local MLX model directory is no longer available")
            ModelHolder.get_model(str(self.model_dir), mx.float16)
            self._loaded = True

    async def transcribe(
        self,
        pcm: bytes,
        *,
        sample_rate_hz: int,
        channels: int,
        source: AudioSource,
        final: bool = False,
    ) -> list[TranscriptionChunk]:
        """Transcribe bounded PCM windows without sending audio to a file or service."""
        await self.load()
        audio = _resample_mono(_pcm_to_float32(pcm, channels), sample_rate_hz)
        if audio.size == 0 or not np.any(audio):
            return []

        def _transcribe() -> list[TranscriptionChunk]:
            import mlx_whisper

            with self._model_lock:
                if not self.model_dir.is_dir():
                    raise ValueError("Local MLX model directory is no longer available")
                result = mlx_whisper.transcribe(
                    audio,
                    path_or_hf_repo=str(self.model_dir),
                    language="en",
                    temperature=0.0,
                    condition_on_previous_text=False,
                    verbose=None,
                )
                duration_ms = round(audio.size * 1_000 / 16_000)
                chunks = []
                for segment in result["segments"]:
                    text = str(segment["text"]).strip()
                    start = max(0, min(duration_ms, int(float(segment["start"]) * 1_000)))
                    end = max(start, min(duration_ms, int(float(segment["end"]) * 1_000)))
                    if text and end > start:
                        chunks.append(TranscriptionChunk(text=text, start_ms=start, end_ms=end))
                return chunks

        return await asyncio.to_thread(_transcribe)


_default_engine: TranscriptionEngine | None = None


async def check_local_asr_readiness(
    *,
    timeout_seconds: float = ASR_READINESS_TIMEOUT_SECONDS,
    engine_factory: Callable[[], Any] | None = None,
) -> tuple[bool, str]:
    """Bound the local ASR model load used by health/readiness checks.

    The default engine validates ``settings.asr_model_dir`` and loads it with
    ``local_files_only=True``.  ``engine_factory`` keeps this check unit-testable
    without importing or loading a real model.
    """
    if timeout_seconds <= 0:
        return False, "ASR readiness timeout must be positive"

    try:
        if engine_factory is None:
            engine = get_local_asr_engine()
        else:
            engine = await asyncio.to_thread(engine_factory)
        ready, message = await ensure_local_asr_ready(engine, timeout_seconds=timeout_seconds)
        return ready, message
    except asyncio.TimeoutError:
        return False, "Local ASR readiness check timed out"
    except Exception as exc:
        return False, str(exc) or "Local ASR is unavailable"


def get_local_asr_engine() -> TranscriptionEngine:
    """Return the process-wide local ASR engine used by readiness and capture."""
    global _default_engine
    if _default_engine is None:
        _default_engine = (
            MLXWhisperTranscriptionEngine()
            if settings.asr_backend == "mlx-whisper"
            else FasterWhisperTranscriptionEngine()
        )
    return _default_engine


async def ensure_local_asr_ready(
    engine: Any,
    *,
    timeout_seconds: float = ASR_READINESS_TIMEOUT_SECONDS,
) -> tuple[bool, str]:
    """Bound the required ASR load without cancelling an underlying load task."""
    if timeout_seconds <= 0:
        return False, "ASR readiness timeout must be positive"
    load = getattr(engine, "load", None)
    if load is None:
        return True, "OK — local ASR model is ready"
    try:
        await asyncio.wait_for(asyncio.shield(load()), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        return False, "Local ASR readiness check timed out"
    except Exception as exc:
        return False, str(exc) or "Local ASR is unavailable"
    return True, "OK — local ASR model is ready"


def _require_model_dir(model_dir: str | Path | None) -> Path:
    """Validate the pre-provisioned absolute small.en model directory."""
    if model_dir is None or not str(model_dir).strip():
        raise ValueError("ASR_MODEL_DIR must point to an absolute local small.en directory")
    path = Path(model_dir).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise ValueError("ASR_MODEL_DIR must be an existing absolute directory")
    if path.name != "small.en":
        raise ValueError("ASR_MODEL_DIR must be the small.en CTranslate2 directory")
    return path.resolve()


def _pcm_to_float32(pcm: bytes, channels: int) -> np.ndarray:
    """Convert bounded little-endian signed-16 PCM to a mono NumPy waveform."""
    if channels <= 0:
        raise ValueError("channels must be positive")
    if len(pcm) % (2 * channels) != 0:
        raise ValueError("PCM payload is not aligned to its channel count")
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / np.float32(32_768.0)
    if channels == 1:
        return samples
    return samples.reshape(-1, channels).mean(axis=1, dtype=np.float32)


def _resample_mono(
    samples: np.ndarray,
    sample_rate_hz: int,
    target_rate_hz: int = 16_000,
) -> np.ndarray:
    """Linearly resample a mono NumPy waveform to faster-whisper's 16 kHz rate."""
    samples = np.asarray(samples, dtype=np.float32)
    if sample_rate_hz == target_rate_hz or samples.size == 0:
        return samples
    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive")
    output_length = max(1, round(len(samples) * target_rate_hz / sample_rate_hz))
    positions = np.linspace(0, len(samples) - 1, output_length, dtype=np.float32)
    return np.interp(positions, np.arange(len(samples)), samples).astype(np.float32)


__all__ = [
    "ASR_READINESS_TIMEOUT_SECONDS",
    "ensure_local_asr_ready",
    "FakeTranscriptionEngine",
    "FasterWhisperTranscriptionEngine",
    "get_local_asr_engine",
    "TranscriptionChunk",
    "TranscriptionEngine",
    "check_local_asr_readiness",
]
