"""Tests for offline transcription engine configuration and fake behavior."""

from __future__ import annotations

import asyncio
import sys
import types

from typing import Any

import pytest

from app.models.enums import AudioSource
from app.services.transcription import (
    FakeTranscriptionEngine,
    FasterWhisperTranscriptionEngine,
    TranscriptionChunk,
    check_local_asr_readiness,
    _resample_mono,
)


def test_production_engine_requires_absolute_small_en_directory(tmp_path):
    with pytest.raises(ValueError, match="absolute"):
        FasterWhisperTranscriptionEngine("small.en")
    with pytest.raises(ValueError, match="small.en"):
        FasterWhisperTranscriptionEngine(tmp_path)


async def test_production_engine_loads_offline_cpu_int8(monkeypatch, tmp_path):
    model_dir = tmp_path / "small.en"
    model_dir.mkdir()
    captured: dict[str, object] = {}

    class FakeWhisperModel:
        def __init__(self, path, **kwargs):
            captured["path"] = path
            captured.update(kwargs)

        def transcribe(self, audio, **kwargs):
            captured["audio"] = audio
            captured["transcribe_kwargs"] = kwargs
            return [], None

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeWhisperModel))
    engine = FasterWhisperTranscriptionEngine(model_dir)
    await engine.load()

    assert captured == {
        "path": str(model_dir.resolve()),
        "device": "cpu",
        "compute_type": "int8",
        "local_files_only": True,
    }


async def test_production_engine_reuses_one_concurrent_model_load(monkeypatch, tmp_path):
    model_dir = tmp_path / "small.en"
    model_dir.mkdir()
    load_calls = 0

    class FakeWhisperModel:
        def __init__(self, path, **kwargs):
            pass

    async def delayed_to_thread(function, *args, **kwargs):
        nonlocal load_calls
        load_calls += 1
        await asyncio.sleep(0.01)
        return function(*args, **kwargs)

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeWhisperModel))
    monkeypatch.setattr("app.services.transcription.asyncio.to_thread", delayed_to_thread)
    engine = FasterWhisperTranscriptionEngine(model_dir)

    await asyncio.gather(*(engine.load() for _ in range(5)))

    assert load_calls == 1


async def test_local_asr_readiness_is_loadable_and_bounded():
    class ReadyEngine:
        async def load(self):
            return None

    ready, message = await check_local_asr_readiness(
        timeout_seconds=0.1,
        engine_factory=ReadyEngine,
    )

    assert ready is True
    assert message == "OK — local ASR model is ready"


async def test_local_asr_readiness_times_out():
    class SlowEngine:
        async def load(self):
            await asyncio.sleep(1)

    ready, message = await check_local_asr_readiness(
        timeout_seconds=0.001,
        engine_factory=SlowEngine,
    )

    assert ready is False
    assert message == "Local ASR readiness check timed out"


async def test_production_engine_resamples_pcm_for_whisper(monkeypatch, tmp_path):
    model_dir = tmp_path / "small.en"
    model_dir.mkdir()
    observed: dict[str, Any] = {}

    class FakeWhisperModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio, **kwargs):
            observed["audio"] = audio
            observed["kwargs"] = kwargs
            return [], None

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeWhisperModel))
    engine = FasterWhisperTranscriptionEngine(model_dir)
    await engine.transcribe(
        b"\0" * 16,
        sample_rate_hz=8_000,
        channels=1,
        source=AudioSource.SYSTEM,
        final=True,
    )

    assert len(observed["audio"]) == 16
    assert observed["kwargs"] == {"language": "en", "vad_filter": True}


def test_resample_mono_preserves_target_length():
    assert len(_resample_mono([0.0, 1.0, 0.0, 1.0], 8_000)) == 8


async def test_fake_engine_is_deterministic():
    engine = FakeTranscriptionEngine([TranscriptionChunk("hello")])

    result = await engine.transcribe(
        b"\0" * 16,
        sample_rate_hz=8_000,
        channels=1,
        source=AudioSource.MICROPHONE,
        final=True,
    )

    assert result == [TranscriptionChunk("hello")]
    assert engine.calls[0]["final"] is True
