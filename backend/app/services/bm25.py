from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from fastembed import SparseTextEmbedding
from qdrant_client import models

if TYPE_CHECKING:
    from collections.abc import Sequence

BM25_MODEL_NAME = "qdrant/bm25"
BM25_DEFAULTS = {"k": 1.2, "b": 0.75, "avg_len": 256.0}
BM25_LANGUAGES = (
    "arabic",
    "danish",
    "dutch",
    "english",
    "finnish",
    "french",
    "german",
    "greek",
    "hungarian",
    "italian",
    "norwegian",
    "portuguese",
    "romanian",
    "russian",
    "spanish",
    "swedish",
    "tamil",
    "turkish",
)


class Bm25Encoder(Protocol):
    async def embed_documents(
        self, texts: Sequence[str], *, language: str, options: dict[str, object]
    ) -> list[models.SparseVector]: ...

    async def embed_query(
        self, text: str, *, language: str, options: dict[str, object]
    ) -> models.SparseVector: ...


@dataclass(frozen=True)
class Bm25Settings:
    language: str
    k: float
    b: float
    avg_len: float

    @classmethod
    def from_options(cls, *, language: str, options: dict[str, object]) -> Bm25Settings:
        return cls(
            language=language,
            k=float(options["k"]),
            b=float(options["b"]),
            avg_len=float(options["avg_len"]),
        )


class FastEmbedBm25:
    """Produces Qdrant sparse vectors locally without cloud or server-side inference."""

    def __init__(self, *, cache_dir: str | os.PathLike[str] | None = None) -> None:
        self._models: dict[Bm25Settings, SparseTextEmbedding] = {}
        self._models_lock = asyncio.Lock()
        self._cache_dir = (
            str(cache_dir)
            if cache_dir is not None
            else os.environ.get("FASTEMBED_CACHE_PATH") or None
        )

    async def embed_documents(
        self, texts: Sequence[str], *, language: str, options: dict[str, object]
    ) -> list[models.SparseVector]:
        model = await self._model(language=language, options=options)
        embeddings = await asyncio.to_thread(lambda: list(model.embed(list(texts))))
        return [_to_sparse_vector(embedding.indices, embedding.values) for embedding in embeddings]

    async def embed_query(
        self, text: str, *, language: str, options: dict[str, object]
    ) -> models.SparseVector:
        model = await self._model(language=language, options=options)
        embeddings = await asyncio.to_thread(lambda: list(model.query_embed(text)))
        if len(embeddings) != 1:
            raise RuntimeError("FastEmbed BM25 returned an invalid query embedding.")
        return _to_sparse_vector(embeddings[0].indices, embeddings[0].values)

    async def _model(self, *, language: str, options: dict[str, object]) -> SparseTextEmbedding:
        settings = Bm25Settings.from_options(language=language, options=options)
        async with self._models_lock:
            model = self._models.get(settings)
            if model is None:
                model = await asyncio.to_thread(
                    SparseTextEmbedding,
                    BM25_MODEL_NAME,
                    cache_dir=self._cache_dir,
                    k=settings.k,
                    b=settings.b,
                    avg_len=settings.avg_len,
                    language=settings.language,
                )
                self._models[settings] = model
            return model


def _to_sparse_vector(indices: object, values: object) -> models.SparseVector:
    return models.SparseVector(
        indices=list(indices.tolist()),
        values=list(values.tolist()),
    )
