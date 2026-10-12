"""Local ASR latency and embedding retrieval comparisons; never modify application indexes."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, Field, model_validator

from app.api.middleware.error_handler import AppError
from app.models.enums import AudioSource
from app.services.embeddings import EmbeddingService
from app.services.transcription import (
    FasterWhisperTranscriptionEngine,
    MLXWhisperTranscriptionEngine,
    TranscriptionEngine,
)


class RetrievalDocument(BaseModel):
    """One labeled corpus passage."""

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class RetrievalQuestion(BaseModel):
    """A query and the passage IDs that answer it."""

    query: str = Field(min_length=1)
    relevant_ids: list[str] = Field(min_length=1)


class RetrievalDataset(BaseModel):
    """Validated benchmark corpus, independent of persisted Chroma data."""

    documents: list[RetrievalDocument] = Field(min_length=1)
    questions: list[RetrievalQuestion] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_ids(self) -> RetrievalDataset:
        """Reject duplicate passage IDs and labels absent from the corpus."""
        ids = {document.id for document in self.documents}
        if len(ids) != len(self.documents):
            raise ValueError("Document IDs must be unique")
        if any(not set(question.relevant_ids) <= ids for question in self.questions):
            raise ValueError("Question labels must reference existing document IDs")
        return self


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Compute case/punctuation-insensitive edit distance per reference word."""
    expected = re.findall(r"\w+", reference.lower())
    actual = re.findall(r"\w+", hypothesis.lower())
    if not expected:
        raise ValueError("A reference must contain words")
    previous = list(range(len(actual) + 1))
    for index, word in enumerate(expected, 1):
        current = [index]
        for offset, found in enumerate(actual, 1):
            current.append(
                min(
                    previous[offset] + 1,
                    current[-1] + 1,
                    previous[offset - 1] + (word != found),
                )
            )
        previous = current
    return previous[-1] / len(expected)


async def benchmark_asr(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Measure actual application-sized PCM windows using explicitly local models."""
    with wave.open(str(args.audio), "rb") as audio:
        if audio.getsampwidth() != 2 or audio.getcomptype() != "NONE":
            raise ValueError("Audio must be uncompressed signed-16 PCM WAV")
        rate, channels = audio.getframerate(), audio.getnchannels()
        pcm = audio.readframes(audio.getnframes())
    size = round(rate * args.window_ms / 1_000) * channels * 2
    if not pcm or size <= 0 or args.repeats <= 0:
        raise ValueError("Audio, window duration, and repeat count must be positive")
    engines: list[tuple[str, TranscriptionEngine]] = [
        ("faster-whisper", FasterWhisperTranscriptionEngine(args.cpu_model_dir)),
    ]
    if args.mlx_model_dir:
        engines.append(("mlx-whisper", MLXWhisperTranscriptionEngine(args.mlx_model_dir)))
    results = []
    for name, engine in engines:
        try:
            started = time.perf_counter()
            await engine.load()
            load_seconds = time.perf_counter() - started
            latencies = []
            transcript = []
            for repeat in range(args.repeats):
                for offset in range(0, len(pcm), size):
                    started = time.perf_counter()
                    chunks = await engine.transcribe(
                        pcm[offset : offset + size],
                        sample_rate_hz=rate,
                        channels=channels,
                        source=AudioSource.SYSTEM,
                    )
                    latencies.append(time.perf_counter() - started)
                    if repeat == 0:
                        transcript.extend(chunk.text for chunk in chunks)
            result = {
                "engine": name,
                "load_seconds": load_seconds,
                "window_ms": args.window_ms,
                "samples": len(latencies),
                "p50_ms": float(np.percentile(latencies, 50) * 1_000),
                "p95_ms": float(np.percentile(latencies, 95) * 1_000),
                "real_time_factor": sum(latencies)
                / (len(pcm) / (rate * channels * 2) * args.repeats),
            }
            if args.reference:
                result["word_error_rate"] = word_error_rate(
                    args.reference.read_text(),
                    " ".join(transcript),
                )
            results.append(result)
        finally:
            await engine.close()
    return results


async def benchmark_embeddings(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Compare retrieval quality in memory with identical passages for every model."""
    dataset = RetrievalDataset.model_validate_json(args.dataset.read_text())
    results = []
    for model in args.models:
        service = EmbeddingService(model)
        identity = await service.get_identity()
        started = time.perf_counter()
        vectors = np.asarray(await service.embed_texts([doc.text for doc in dataset.documents]))
        ingestion_seconds = time.perf_counter() - started
        latencies, recalls, ranks = [], [], []
        for question in dataset.questions:
            started = time.perf_counter()
            query = np.asarray(await service.embed_text(question.query))
            norms = np.linalg.norm(vectors, axis=1) * np.linalg.norm(query)
            scores = (vectors @ query) / np.maximum(norms, 1e-12)
            order = np.argsort(-scores)
            relevant = set(question.relevant_ids)
            ranked = [dataset.documents[index].id for index in order]
            recalls.append(len(set(ranked[:5]) & relevant) / len(relevant))
            first = next(index for index, item in enumerate(ranked, 1) if item in relevant)
            ranks.append(1 / first)
            latencies.append(time.perf_counter() - started)
        if await service.get_identity() != identity:
            raise ValueError("Model weights changed during the benchmark")
        results.append(
            {
                **identity,
                "dimension": int(vectors.shape[1]),
                "recall_at_5": float(np.mean(recalls)),
                "mean_reciprocal_rank": float(np.mean(ranks)),
                "ingestion_seconds": ingestion_seconds,
                "query_p95_ms": float(np.percentile(latencies, 95) * 1_000),
                "questions": len(dataset.questions),
            }
        )
    return results


def main() -> None:
    """Run a requested local comparison and print JSON metrics."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    asr = commands.add_parser("asr")
    asr.add_argument("audio", type=Path)
    asr.add_argument("--cpu-model-dir", type=Path, required=True)
    asr.add_argument("--mlx-model-dir", type=Path)
    asr.add_argument("--reference", type=Path)
    asr.add_argument("--window-ms", type=int, default=2_000)
    asr.add_argument("--repeats", type=int, default=3)
    embeddings = commands.add_parser("embeddings")
    embeddings.add_argument("dataset", type=Path)
    embeddings.add_argument(
        "--models",
        nargs="+",
        default=[
            "nomic-embed-text",
            "qwen3-embedding:0.6b",
            "embeddinggemma",
        ],
    )
    args = parser.parse_args()
    try:
        result = asyncio.run(
            benchmark_asr(args) if args.command == "asr" else benchmark_embeddings(args)
        )
    except (AppError, ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f"Benchmark failed: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
