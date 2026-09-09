"""ChromaDB vector store operations for RAG."""

from __future__ import annotations

import asyncio
from typing import Any

import chromadb
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


class VectorStoreService:
    """Manages ChromaDB collections for document embeddings and semantic search.

    Design decisions:
        - Persistent storage on disk (survives restarts).
        - One collection per logical document group (default: "documents").
        - Embeddings generated via Ollama (nomic-embed-text) through EmbeddingService.
        - Similarity search with configurable score threshold and top-k.
        - All ChromaDB calls run in asyncio.to_thread() to avoid blocking the event loop.
    """

    def __init__(self) -> None:
        self._client: chromadb.ClientAPI | None = None

    def _get_client(self) -> chromadb.ClientAPI:
        """Lazy-initialize the ChromaDB client.

        When ``settings.chroma_host`` is set (e.g. in Docker), an HTTP client
        is used to reach a remote ChromaDB instance.  Otherwise a local
        persistent client is created.
        """
        if self._client is None:
            if settings.chroma_host:
                self._client = chromadb.HttpClient(
                    host=settings.chroma_host,
                    port=settings.chroma_port,
                )
            else:
                self._client = chromadb.PersistentClient(
                    path=str(settings.chroma_path),
                )
        return self._client

    def _get_or_create_collection(self, name: str | None = None) -> chromadb.Collection:
        """Get an existing collection or create a new one (sync).

        Args:
            name: Collection name. Defaults to settings.chroma_collection_name.

        Returns:
            A ChromaDB Collection.
        """
        client = self._get_client()
        collection_name = name or settings.chroma_collection_name
        return client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    async def add_documents(
        self,
        texts: list[str],
        metadatas: list[dict[str, Any]],
        ids: list[str],
        collection: str | None = None,
    ) -> int:
        """Embed and store documents in the vector store.

        Args:
            texts: Document text chunks.
            metadatas: Per-chunk metadata (source, page, section, etc.).
            ids: Unique IDs for each chunk.
            collection: Target collection name.

        Returns:
            Number of documents added.
        """
        if not texts:
            return 0

        from app.services.embeddings import embedding_service

        embeddings = await embedding_service.embed_texts(texts)

        def _add() -> None:
            col = self._get_or_create_collection(collection)
            col.add(
                documents=texts,
                embeddings=embeddings,
                metadatas=metadatas,
                ids=ids,
            )

        await asyncio.to_thread(_add)
        logger.info(
            "documents_added",
            count=len(texts),
            collection=collection or settings.chroma_collection_name,
        )
        return len(texts)

    async def search(
        self,
        query: str,
        collection: str | None = None,
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        """Perform semantic similarity search.

        Args:
            query: The search query text.
            collection: Target collection name.
            top_k: Maximum number of results.
            score_threshold: Minimum similarity score (0-1, cosine).

        Returns:
            List of result dicts with keys: content, score, metadata.
        """
        from app.services.embeddings import embedding_service

        k = top_k or settings.rag_top_k
        threshold = score_threshold or settings.rag_score_threshold

        query_embedding = await embedding_service.embed_text(query)

        def _query() -> dict[str, Any]:
            col = self._get_or_create_collection(collection)
            return col.query(
                query_embeddings=[query_embedding],
                n_results=k,
                include=["documents", "metadatas", "distances"],
            )

        results = await asyncio.to_thread(_query)

        items: list[dict[str, Any]] = []
        if results["documents"] and results["documents"][0]:
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                # ChromaDB returns cosine distance; convert to similarity
                score = 1 - dist
                if score >= threshold:
                    items.append(
                        {
                            "content": doc,
                            "score": round(score, 4),
                            "metadata": meta or {},
                        }
                    )

        logger.debug(
            "vector_search",
            query_length=len(query),
            results=len(items),
            collection=collection or settings.chroma_collection_name,
        )
        return items

    async def list_collections(self) -> list[dict[str, Any]]:
        """List all collections with document counts."""

        def _list() -> list[dict[str, Any]]:
            client = self._get_client()
            collections = client.list_collections()
            result = []
            for col in collections:
                # ChromaDB >= 0.5 returns Collection objects from list_collections()
                if isinstance(col, str):
                    collection = client.get_collection(col)
                    name = col
                else:
                    collection = col
                    name = col.name
                result.append(
                    {
                        "name": name,
                        "document_count": collection.count(),
                        "metadata": collection.metadata or {},
                    }
                )
            return result

        return await asyncio.to_thread(_list)

    async def delete_collection(self, name: str) -> bool:
        """Delete a collection by name.

        Returns:
            True if deleted, False if not found.
        """

        def _delete() -> bool:
            try:
                self._get_client().delete_collection(name)
                logger.info("collection_deleted", name=name)
                return True
            except ValueError:
                return False

        return await asyncio.to_thread(_delete)

    async def get_collection_count(self, name: str | None = None) -> int:
        """Get the number of documents in a collection."""

        def _count() -> int:
            col = self._get_or_create_collection(name)
            return col.count()

        return await asyncio.to_thread(_count)


# Module-level singleton (lazy-initialized, no side effects at import time)
vector_store_service = VectorStoreService()
