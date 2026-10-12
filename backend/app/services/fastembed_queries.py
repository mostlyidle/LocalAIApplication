"""Query embeddings for the loader's Nomic FastEmbed collection contract."""

import asyncio
import math
import os
from collections.abc import Sequence
from pathlib import Path

from fastembed import TextEmbedding

from app.services.rag_store import RagStoreUnavailableError

LOADER_EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5"
LOADER_EMBEDDING_REVISION = "fastembed-nomic-v1.5-v1"
LOADER_EMBEDDING_DIMENSION = 768


class FastEmbedQueries:
    def __init__(self, *, cache_dir: str | Path | None = None) -> None:
        self._model: TextEmbedding | None = None
        self._inference_slot = asyncio.Semaphore(1)
        self._cache_dir = (
            str(cache_dir)
            if cache_dir is not None
            else os.environ.get("FASTEMBED_CACHE_PATH") or None
        )

    async def embed(self, inputs: Sequence[str]) -> list[list[float]]:
        if not inputs:
            return []
        await self._inference_slot.acquire()
        try:
            task = asyncio.create_task(asyncio.to_thread(self._embed, inputs))
        except BaseException:
            self._inference_slot.release()
            raise
        release_on_completion = False
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            release_on_completion = True
            task.add_done_callback(self._release_after_cancel)
            raise
        except Exception as exc:
            raise RagStoreUnavailableError("FastEmbed could not encode the RAG queries.") from exc
        finally:
            if not release_on_completion:
                self._inference_slot.release()

    def _release_after_cancel(self, task: asyncio.Task[list[list[float]]]) -> None:
        if not task.cancelled():
            task.exception()
        self._inference_slot.release()

    def _embed(self, inputs: Sequence[str]) -> list[list[float]]:
        if self._model is None:
            self._model = TextEmbedding(
                model_name=LOADER_EMBEDDING_MODEL,
                cache_dir=self._cache_dir,
                providers=["CPUExecutionProvider"],
            )
        vectors = [
            [float(value) for value in vector]
            for vector in self._model.query_embed(
                [f"search_query: {text}" for text in inputs], batch_size=32
            )
        ]
        if len(vectors) != len(inputs) or any(
            len(vector) != LOADER_EMBEDDING_DIMENSION
            or not all(math.isfinite(value) for value in vector)
            for vector in vectors
        ):
            raise ValueError("FastEmbed returned invalid query embeddings.")
        return vectors
