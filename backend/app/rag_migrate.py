"""Inventory, dry-run, and explicitly migrate Chroma collections to Qdrant."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import chromadb

from app.config import settings
from app.services.bm25 import FastEmbedBm25
from app.services.embeddings import embedding_service
from app.services.rag_store import RagStore

IDENTITY_FIELDS = ("embedding_model", "embedding_digest", "embedding_profile")


@dataclass(frozen=True)
class ChromaCollectionInventory:
    name: str
    chunk_count: int
    metadata: dict[str, Any]
    embedding_dimension: int | None
    identity_complete: bool


@dataclass(frozen=True)
class MigrationReport:
    source_collection: str
    destination_collection: str
    chunk_count: int
    asset_count: int
    dense_vectors: str
    source_ids_verified: bool
    citation_metadata_verified: bool
    source_preserved: bool = True


def inventory_chroma(source_path: str | Path) -> list[ChromaCollectionInventory]:
    """Read collection names, counts, and embedding identity without exporting text."""
    path = _existing_source_path(source_path)
    client = chromadb.PersistentClient(path=str(path))
    try:
        collections = []
        for collection in client.list_collections():
            metadata = dict(collection.metadata or {})
            dimension = metadata.get("embedding_dimension")
            collections.append(
                ChromaCollectionInventory(
                    name=collection.name,
                    chunk_count=collection.count(),
                    metadata={
                        key: metadata[key]
                        for key in (*IDENTITY_FIELDS, "embedding_dimension", "hnsw:space")
                        if key in metadata
                    },
                    embedding_dimension=dimension if isinstance(dimension, int) else None,
                    identity_complete=all(
                        isinstance(metadata.get(key), str) and metadata[key]
                        for key in IDENTITY_FIELDS
                    )
                    and isinstance(dimension, int),
                )
            )
        return sorted(collections, key=lambda item: item.name)
    finally:
        client.close()


def dry_run_chroma_migration(
    *, source_path: str | Path, source_collection: str, destination_collection: str
) -> dict[str, object]:
    """Describe migration work without connecting to Ollama or writing Qdrant."""
    inventory = {item.name: item for item in inventory_chroma(source_path)}
    source = inventory.get(source_collection)
    if source is None:
        raise ValueError(f"Chroma collection '{source_collection}' does not exist.")
    return {
        "mode": "dry_run",
        "source_path": str(_existing_source_path(source_path)),
        "source_collection": source.name,
        "source_chunks": source.chunk_count,
        "source_embedding_identity": source.metadata,
        "destination_collection": destination_collection,
        "destination_reservation": "not_checked_or_created_until_execute",
        "dense_vectors": (
            "reuse_only_after_runtime_identity_match"
            if source.identity_complete
            else "reembed_with_current_ollama_model"
        ),
        "bm25_vectors": "generate_locally_during_migration",
        "source_data": "preserved",
    }


async def migrate_chroma_collection(
    *,
    source_path: str | Path,
    source_collection: str,
    destination_collection: str,
    qdrant_url: str,
    language: str | None = None,
    source_client: Any | None = None,
    destination_store: RagStore | None = None,
) -> MigrationReport:
    """Copy one collection into a new Qdrant collection, retaining Chroma intact.

    A failed copy leaves its reserved destination for inspection. Retry with a new
    destination name; this function never deletes or overwrites migration data.
    """
    path = _existing_source_path(source_path)
    owns_source = source_client is None
    owns_destination = destination_store is None
    source = source_client or chromadb.PersistentClient(path=str(path))
    destination = destination_store or RagStore(
        qdrant_url,
        bm25_encoder=FastEmbedBm25(cache_dir=settings.fastembed_cache_path),
    )
    try:
        collection = source.get_collection(source_collection)
        source_metadata = dict(collection.metadata or {})
        records = await asyncio.to_thread(
            collection.get,
            include=["documents", "metadatas", "embeddings"],
        )
        rows = _preflight_records(records)
        identity = await embedding_service.get_identity()
        dimension = settings.ollama_embedding_dimension
        vectors_match = _source_identity_matches(
            source_metadata, identity=identity, dimension=dimension
        ) and all(len(row["embedding"]) == dimension for row in rows)

        if vectors_match:
            dense_vectors = [row["embedding"] for row in rows]
            vector_source = "reused_verified_source_vectors"
        else:
            dense_vectors = await embedding_service.embed_texts([row["text"] for row in rows])
            if await embedding_service.get_identity() != identity:
                raise ValueError(
                    "Ollama embedding identity changed during migration; destination was not written."
                )
            vector_source = "reembedded_with_current_ollama_model"
        if len(dense_vectors) != len(rows) or any(
            len(vector) != dimension for vector in dense_vectors
        ):
            raise ValueError("Migration embeddings do not match the configured dimension.")

        revision = ":".join(
            (
                settings.ollama_embedding_revision,
                identity["embedding_digest"],
                identity["embedding_profile"],
            )
        )
        bm25_language = language or settings.rag_bm25_language
        await destination.create_hybrid_collection(
            collection=destination_collection,
            dimension=dimension,
            dense_model=identity["embedding_model"],
            embedding_revision=revision,
            language=bm25_language,
        )
        groups: dict[str, list[tuple[dict[str, Any], list[float]]]] = defaultdict(list)
        for row, vector in zip(rows, dense_vectors, strict=True):
            metadata = row["metadata"]
            asset_id = _asset_id(source_collection, row["id"], metadata)
            groups[asset_id].append((row, vector))
        for asset_id, group in sorted(groups.items()):
            await destination.upsert(
                collection=destination_collection,
                chunks=[row["text"] for row, _ in group],
                embeddings=[vector for _, vector in group],
                asset_id=asset_id,
                dense_model=identity["embedding_model"],
                language=bm25_language,
                embedding_revision=revision,
                expected_dimension=dimension,
                provenance=[
                    {
                        **row["metadata"],
                        "source_chunk_id": row["id"],
                        "document_id": asset_id,
                        "source": row["metadata"].get("source") or row["metadata"].get("filename"),
                        "filename": row["metadata"].get("filename")
                        or row["metadata"].get("source"),
                        "page_start": row["metadata"].get("page_start")
                        or row["metadata"].get("page"),
                    }
                    for row, _ in group
                ],
            )

        migrated_payloads = await destination.collection_source_chunk_payloads(
            destination_collection
        )
        expected_ids = {row["id"] for row in rows}
        count = await destination.get_collection_count(destination_collection)
        ids_verified = set(migrated_payloads) == expected_ids
        citations_verified = ids_verified and all(
            _citation_metadata_matches(row["metadata"], migrated_payloads[row["id"]])
            for row in rows
        )
        verified = count == len(rows) and ids_verified and citations_verified
        if not verified:
            raise RuntimeError(
                "Migration verification failed. The destination remains intact for inspection; "
                "use a new destination name for a retry."
            )
        return MigrationReport(
            source_collection=source_collection,
            destination_collection=destination_collection,
            chunk_count=count,
            asset_count=len(groups),
            dense_vectors=vector_source,
            source_ids_verified=ids_verified,
            citation_metadata_verified=citations_verified,
        )
    finally:
        if owns_source:
            source.close()
        if owns_destination:
            await destination.close()


def _preflight_records(records: Mapping[str, Any]) -> list[dict[str, Any]]:
    ids = records.get("ids")
    documents = records.get("documents")
    metadatas = records.get("metadatas")
    embeddings = records.get("embeddings")
    if (
        not all(isinstance(items, Sequence) for items in (ids, documents, metadatas))
        or embeddings is None
    ):
        raise ValueError("Chroma export is missing IDs, text, metadata, or embeddings.")
    embedding_rows = list(embeddings)
    if not (len(ids) == len(documents) == len(metadatas) == len(embedding_rows)):
        raise ValueError("Chroma export fields have inconsistent lengths.")
    rows = []
    for chunk_id, text, metadata, embedding in zip(
        ids, documents, metadatas, embedding_rows, strict=True
    ):
        if not isinstance(chunk_id, str) or not chunk_id:
            raise ValueError("Every Chroma chunk must have a stable string ID.")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Chroma chunk '{chunk_id}' has no text.")
        dense = [float(value) for value in embedding]
        if not dense:
            raise ValueError(f"Chroma chunk '{chunk_id}' has no dense vector.")
        rows.append(
            {
                "id": chunk_id,
                "text": text,
                "metadata": dict(metadata or {}),
                "embedding": dense,
            }
        )
    return rows


def _source_identity_matches(
    source_metadata: Mapping[str, Any], *, identity: Mapping[str, str], dimension: int
) -> bool:
    return source_metadata.get("embedding_dimension") == dimension and all(
        source_metadata.get(key) == identity[key] for key in IDENTITY_FIELDS
    )


def _asset_id(collection: str, chunk_id: str, metadata: Mapping[str, Any]) -> str:
    for key in ("document_id", "asset_id"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return str(metadata.get("source") or metadata.get("filename") or f"{collection}:{chunk_id}")


def _citation_metadata_matches(
    source: Mapping[str, Any], destination: Mapping[str, object]
) -> bool:
    expected = {
        "filename": source.get("filename") or source.get("source"),
        "source": source.get("source") or source.get("filename"),
        "page_start": source.get("page_start") or source.get("page"),
        "page_end": source.get("page_end"),
        "section": source.get("section"),
    }
    return all(
        destination.get(key) == value for key, value in expected.items() if value is not None
    )


def _existing_source_path(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"Chroma source path does not exist as a directory: {path}")
    return path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inventory = commands.add_parser("inventory", help="list collections and identity metadata")
    inventory.add_argument("--source-path", required=True, type=Path)
    migrate = commands.add_parser("migrate", help="dry-run by default; pass --execute to copy")
    migrate.add_argument("--source-path", required=True, type=Path)
    migrate.add_argument("--source-collection", required=True)
    migrate.add_argument("--destination-collection", required=True)
    migrate.add_argument("--qdrant-url", default=settings.qdrant_url)
    migrate.add_argument("--language", default=settings.rag_bm25_language)
    migrate.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.command == "inventory":
        result = [asdict(item) for item in inventory_chroma(args.source_path)]
    elif args.execute:
        result = asdict(
            asyncio.run(
                migrate_chroma_collection(
                    source_path=args.source_path,
                    source_collection=args.source_collection,
                    destination_collection=args.destination_collection,
                    qdrant_url=args.qdrant_url,
                    language=args.language,
                )
            )
        )
    else:
        result = dry_run_chroma_migration(
            source_path=args.source_path,
            source_collection=args.source_collection,
            destination_collection=args.destination_collection,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
