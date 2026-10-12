"""MLX speech integration tests without model downloads or GPU inference."""

from __future__ import annotations

import asyncio
import sys
import threading
import time
import types
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import numpy as np
import pytest

from app.models.enums import AudioSource
from app.services.transcription import MLXWhisperTranscriptionEngine, get_local_asr_engine

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def mlx_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a local model layout and deterministic fake MLX modules."""
    monkeypatch.setattr("app.services.transcription.platform.system", lambda: "Darwin")
    monkeypatch.setattr("app.services.transcription.platform.machine", lambda: "arm64")
    monkeypatch.setattr(
        "app.services.transcription.platform.mac_ver", lambda: ("26.0", (), "arm64")
    )
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "weights.npz").write_bytes(b"fixture")
    core = types.ModuleType("mlx.core")
    core.float16 = "float16"
    mlx = types.ModuleType("mlx")
    mlx.core = core
    holder = types.SimpleNamespace(get_model=MagicMock())
    transcribe_module = types.ModuleType("mlx_whisper.transcribe")
    transcribe_module.ModelHolder = holder
    whisper = types.ModuleType("mlx_whisper")
    whisper.transcribe = MagicMock(
        return_value={
            "segments": [
                {"text": " Question? ", "start": 0.1, "end": 0.4},
            ]
        }
    )
    for name, module in (
        ("mlx", mlx),
        ("mlx.core", core),
        ("mlx_whisper", whisper),
        ("mlx_whisper.transcribe", transcribe_module),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    return tmp_path


def test_requires_provisioned_local_model(mlx_model: Path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        MLXWhisperTranscriptionEngine("mlx-community/whisper-small.en")
    with pytest.raises(ValueError, match="weights"):
        MLXWhisperTranscriptionEngine(mlx_model.parent)


def test_older_macos_has_actionable_cpu_fallback(
    mlx_model: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.transcription.platform.mac_ver", lambda: ("14.0", (), "arm64")
    )
    with pytest.raises(ValueError, match="macOS 26"):
        MLXWhisperTranscriptionEngine(mlx_model)


async def test_normalizes_pcm_and_maps_segments(mlx_model: Path) -> None:
    engine = MLXWhisperTranscriptionEngine(mlx_model)
    pcm = np.full(48_000 * 2, 1_000, dtype="<i2").tobytes()
    chunks = await engine.transcribe(
        pcm,
        sample_rate_hz=48_000,
        channels=2,
        source=AudioSource.SYSTEM,
    )
    assert chunks[0].text == "Question?"
    assert (chunks[0].start_ms, chunks[0].end_ms) == (100, 400)
    transcribe = sys.modules["mlx_whisper"].transcribe
    audio = transcribe.call_args.args[0]
    assert audio.shape == (16_000,)
    assert transcribe.call_args.kwargs["path_or_hf_repo"] == str(mlx_model)
    assert transcribe.call_args.kwargs["condition_on_previous_text"] is False


async def test_silence_does_not_generate_text(mlx_model: Path) -> None:
    engine = MLXWhisperTranscriptionEngine(mlx_model)
    chunks = await engine.transcribe(
        bytes(32_000),
        sample_rate_hz=16_000,
        channels=1,
        source=AudioSource.MICROPHONE,
    )
    assert chunks == []
    sys.modules["mlx_whisper"].transcribe.assert_not_called()


async def test_load_is_shared_across_concurrent_readiness(mlx_model: Path) -> None:
    engine = MLXWhisperTranscriptionEngine(mlx_model)
    await asyncio.gather(*(engine.load() for _ in range(5)))
    holder = sys.modules["mlx_whisper.transcribe"].ModelHolder
    holder.get_model.assert_called_once_with(str(mlx_model), "float16")


async def test_failed_native_load_is_not_retried(mlx_model: Path) -> None:
    holder = sys.modules["mlx_whisper.transcribe"].ModelHolder
    holder.get_model.side_effect = RuntimeError("Metal unavailable")
    engine = MLXWhisperTranscriptionEngine(mlx_model)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="Metal unavailable"):
            await engine.load()
    holder.get_model.assert_called_once()


async def test_cancelled_worker_stays_serialized(mlx_model: Path) -> None:
    active = 0
    maximum = 0
    started = threading.Event()

    def slow_transcribe(*args: object, **kwargs: object) -> dict:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        started.set()
        time.sleep(0.03)
        active -= 1
        return {"segments": []}

    sys.modules["mlx_whisper"].transcribe.side_effect = slow_transcribe
    engine = MLXWhisperTranscriptionEngine(mlx_model)
    pcm = np.ones(16_000, dtype="<i2").tobytes()
    options = {"sample_rate_hz": 16_000, "channels": 1, "source": AudioSource.SYSTEM}
    first = asyncio.create_task(engine.transcribe(pcm, **options))
    assert await asyncio.to_thread(started.wait, 1)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    await engine.transcribe(pcm, **options)
    assert maximum == 1


def test_factory_uses_configured_backend(mlx_model: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.transcription._default_engine", None)
    monkeypatch.setattr("app.services.transcription.settings.asr_backend", "mlx-whisper")
    monkeypatch.setattr("app.services.transcription.settings.asr_model_dir", str(mlx_model))
    assert isinstance(get_local_asr_engine(), MLXWhisperTranscriptionEngine)
