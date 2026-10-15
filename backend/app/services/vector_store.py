"""Shared interface for the application's vector-store implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app.services.rag_store import CollectionCapabilities, RagSearchResult


class VectorStoreService(Protocol):
    """Operations required by routes and workers that use the Qdrant store."""

    async def collection_capabilities(self, collection: str) -> CollectionCapabilities | None: ...

    async def add_documents(
        self,
        texts: list[str],
        metadatas: list[dict[str, Any]],
        ids: list[str],
        collection: str | None = None,
        language: str | None = None,
    ) -> int: ...

    async def search(
        self,
        query: str,
        collection: str | None = None,
        top_k: int | None = None,
        score_threshold: float | None = None,
        agent_name: str = "rag",
        rewrite_model: str | None = None,
        owner_id: str | None = None,
    ) -> list[dict[str, Any]]: ...

    async def search_with_provenance(
        self,
        *,
        query: str,
        collection: str,
        top_k: int,
        score_threshold: float | None = None,
        agent_name: str = "rag",
        rewrite_model: str | None = None,
        _bypass_laya_rewrite: bool = False,
    ) -> RagSearchResult: ...

    async def list_collections(self) -> list[dict[str, Any]]: ...

    async def delete_collection(self, name: str) -> bool: ...

    async def delete_asset(self, collection: str, asset_id: str) -> bool: ...

    async def get_collection_count(self, name: str | None = None) -> int: ...
