"""Ollama embedding service for RAG document embeddings."""

from __future__ import annotations

from typing import Sequence

import httpx
import structlog
from langchain_ollama import OllamaEmbeddings

from app.api.middleware.error_handler import InputValidationError, LLMConnectionError
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
        if self._model.split(":")[0] == "qwen3-embedding":
            text = "Instruct: Retrieve relevant passages that answer the query\nQuery: " + text
        elif self._model.split(":")[0] == "embeddinggemma":
            text = "task: search result | query: " + text
        return await self._embeddings.aembed_query(text)

    async def get_identity(self) -> dict[str, str]:
        """Identify installed weights and formatting to prevent mixing embedding spaces."""
        expected_name = self._model if ":" in self._model else self._model + ":latest"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{settings.ollama_base_url}/api/tags")
                response.raise_for_status()
                inventory = response.json()
                if not isinstance(inventory, dict) or not isinstance(inventory.get("models"), list):
                    raise ValueError("Malformed local model inventory")
                for model in inventory["models"]:
                    if (
                        isinstance(model, dict)
                        and model.get("name") == expected_name
                        and isinstance(model.get("digest"), str)
                        and model["digest"]
                    ):
                        return {
                            "embedding_model": expected_name,
                            "embedding_digest": str(model["digest"]),
                            "embedding_profile": self.profile,
                        }
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMConnectionError(
                "Cannot identify the local embedding model in Ollama."
            ) from exc
        raise InputValidationError(f"Embedding model {expected_name} is not installed locally.")

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
        if batch_size <= 0:
            raise ValueError("Embedding batch_size must be positive")
        all_embeddings: list[list[float]] = []
        total = len(texts)

        for i in range(0, total, batch_size):
            batch = list(texts[i : i + batch_size])
            if self._model.split(":")[0] == "embeddinggemma":
                batch = ["title: none | text: " + text for text in batch]
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

    @property
    def profile(self) -> str:
        """Return a versioned input-format identifier; legacy nomic input stays unchanged."""
        family = self._model.split(":")[0]
        if family in {"qwen3-embedding", "embeddinggemma"}:
            return family + "-retrieval-v1"
        return "plain-v1"


# Module-level singleton
embedding_service = EmbeddingService()
