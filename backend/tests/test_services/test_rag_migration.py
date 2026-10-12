from __future__ import annotations

from typing import TYPE_CHECKING

import chromadb
import pytest
from qdrant_client import AsyncQdrantClient

from app.rag_migrate import (
    dry_run_chroma_migration,
    inventory_chroma,
    migrate_chroma_collection,
)
from app.services.rag_store import RagStore
from tests.test_services.test_hybrid_rag import FakeBm25Encoder

if TYPE_CHECKING:
    from pathlib import Path


def _create_chroma_source(path: Path, *, tagged: bool) -> chromadb.ClientAPI:
    client = chromadb.PersistentClient(path=str(path))
    metadata: dict[str, object] = {"hnsw:space": "cosine"}
    if tagged:
        metadata.update(
            {
                "embedding_model": "nomic-embed-text:latest",
                "embedding_digest": "weights-v1",
                "embedding_profile": "plain-v1",
                "embedding_dimension": 768,
            }
        )
    collection = client.create_collection("research", metadata=metadata)
    collection.add(
        ids=["source-chunk-a"],
        documents=["Revenue increased."],
        embeddings=[[0.25] * 768],
        metadatas=[
            {
                "document_id": "report-a",
                "source": "annual-report.pdf",
                "page": 4,
                "page_end": 5,
                "section": "Results",
            }
        ],
    )
    return client


def test_inventory_and_dry_run_report_identity_without_exporting_text(tmp_path: Path) -> None:
    source = _create_chroma_source(tmp_path / "chroma", tagged=True)
    source.close()

    inventory = inventory_chroma(tmp_path / "chroma")
    report = dry_run_chroma_migration(
        source_path=tmp_path / "chroma",
        source_collection="research",
        destination_collection="research",
    )

    assert inventory[0].chunk_count == 1
    assert inventory[0].identity_complete is True
    assert report["source_chunks"] == 1
    assert report["dense_vectors"] == "reuse_only_after_runtime_identity_match"
    assert "text" not in report
    assert report["destination_reservation"] == "not_checked_or_created_until_execute"


@pytest.mark.parametrize("tagged", [True, False])
async def test_migration_preserves_source_ids_citations_and_source_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tagged: bool,
) -> None:
    source_path = tmp_path / "chroma"
    source = _create_chroma_source(source_path, tagged=tagged)
    identity = {
        "embedding_model": "nomic-embed-text:latest",
        "embedding_digest": "weights-v1",
        "embedding_profile": "plain-v1",
    }

    async def get_identity() -> dict[str, str]:
        return identity

    async def embed_texts(texts: list[str]) -> list[list[float]]:
        assert texts == ["Revenue increased."]
        return [[0.5] * 768]

    monkeypatch.setattr("app.rag_migrate.embedding_service.get_identity", get_identity)
    monkeypatch.setattr("app.rag_migrate.embedding_service.embed_texts", embed_texts)
    client = AsyncQdrantClient(path=str(tmp_path / "qdrant"))
    destination = RagStore(
        "http://unused",
        client=client,
        bm25_encoder=FakeBm25Encoder(),
    )
    try:
        report = await migrate_chroma_collection(
            source_path=source_path,
            source_collection="research",
            destination_collection="research",
            qdrant_url="http://unused",
            source_client=source,
            destination_store=destination,
        )

        assert report.chunk_count == 1
        assert report.source_ids_verified is True
        assert report.citation_metadata_verified is True
        assert report.source_preserved is True
        assert source.get_collection("research").count() == 1
        records, _ = await client.scroll("research", with_payload=True, limit=10)
        payload = records[0].payload
        assert payload["source_chunk_id"] == "source-chunk-a"
        assert payload["filename"] == "annual-report.pdf"
        assert payload["page_start"] == 4
        assert payload["page_end"] == 5
        assert payload["section"] == "Results"
        assert report.dense_vectors == (
            "reused_verified_source_vectors" if tagged else "reembedded_with_current_ollama_model"
        )
    finally:
        await destination.close()
        source.close()
