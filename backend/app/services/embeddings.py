"""Ollama embedding service for RAG document embeddings."""

from __future__ import annotations

from typing import Sequence

import structlog
from langchain_ollama import OllamaEmbeddings

from app.config import settings

logger = structlog.get_logger(__name__)


class EmbeddingService:
    """Wrapper around OllamaEmbeddings with batch support.

    Uses nomic-embed-text (768-dim) by default. Supports batching
    to reduce round-trips when embedding large document sets.
    """

    def __init__(self, model: str | None = None) -> None:
        self._model = model or settings.ollama_embedding_model
        self._embeddings = OllamaEmbeddings(
            model=self._model,
            base_url=settings.ollama_base_url,
        )

    async def embed_text(self, text: str) -> list[float]:
        """Embed a single text string.

        Args:
            text: The text to embed.

        Returns:
            A list of floats representing the embedding vector.
        """
        return await self._embeddings.aembed_query(text)

    async def embed_texts(
        self,
        texts: Sequence[str],
        batch_size: int = 32,
    ) -> list[list[float]]:
        """Embed multiple texts in batches.

        Args:
            texts: Sequence of texts to embed.
            batch_size: Number of texts per batch to reduce Ollama round-trips.

        Returns:
            List of embedding vectors, one per input text.
        """
        all_embeddings: list[list[float]] = []
        total = len(texts)

        for i in range(0, total, batch_size):
            batch = list(texts[i : i + batch_size])
            logger.debug(
                "embedding_batch",
                batch_start=i,
                batch_size=len(batch),
                total=total,
            )
            embeddings = await self._embeddings.aembed_documents(batch)
            all_embeddings.extend(embeddings)

        return all_embeddings

    @property
    def model_name(self) -> str:
        return self._model


# Module-level singleton
embedding_service = EmbeddingService()
