"""MCP Server for RAG (Retrieval-Augmented Generation) tools.

Exposes vector store search, document ingestion, and collection management
as an MCP server using the FastMCP high-level API.

Usage:
    python -m app.mcp.servers.rag_server
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import structlog

from mcp.server.fastmcp import FastMCP

logger = structlog.get_logger(__name__)

rag_mcp = FastMCP(
    "RAG Tools",
    instructions="Vector store search, document ingestion, and collection management tools.",
)


@rag_mcp.tool()
async def search_knowledge_base(
    query: str,
    collection: str = "documents",
    top_k: int = 5,
    score_threshold: float = 0.4,
) -> str:
    """Search the knowledge base for relevant information.

    Performs semantic similarity search across ingested documents and returns
    ranked results with relevance scores and source citations.

    Args:
        query: The search query text.
        collection: The collection to search (default: "documents").
        top_k: Maximum number of results to return.
        score_threshold: Minimum similarity score (0-1).
    """
    from app.services.vector_store import vector_store_service

    try:
        results = await vector_store_service.search(
            query=query,
            collection=collection,
            top_k=top_k,
            score_threshold=score_threshold,
        )

        if not results:
            return "No relevant results found in the knowledge base."

        output_parts = []
        for i, r in enumerate(results, 1):
            source = r.get("metadata", {}).get("source", "unknown")
            page = r.get("metadata", {}).get("page", "?")
            score = r.get("score", 0)
            content = r.get("content", "")[:500]
            output_parts.append(
                f"[{i}] Score: {score:.4f} | Source: {source}, Page: {page}\n{content}"
            )

        return "\n\n".join(output_parts)
    except Exception as exc:
        return f"Search error: {exc}"


@rag_mcp.tool()
async def ingest_document(
    file_path: str,
    collection: str = "documents",
) -> str:
    """Ingest a document into the knowledge base for later retrieval.

    Parses the document, splits into chunks, generates embeddings, and
    stores them in the vector store.

    Args:
        file_path: Absolute path to the document file.
        collection: The target collection name.
    """
    from app.models.enums import DocumentFormat
    from app.services.document_parser import document_parser_service
    from app.services.vector_store import vector_store_service

    path = Path(file_path)
    if not path.exists():
        return f"File not found: {file_path}"

    try:
        doc_format = DocumentFormat.from_extension(path.suffix)
    except ValueError as exc:
        return str(exc)

    try:
        parsed = await document_parser_service.parse(path, doc_format)
        chunks = document_parser_service.chunk_text(
            parsed.text,
            metadata={
                "source": path.name,
                "format": doc_format.value,
            },
        )

        if not chunks:
            return "No text content found in document to ingest."

        texts = [c["text"] for c in chunks]
        metadatas = [c["metadata"] for c in chunks]
        doc_id = str(uuid.uuid4())
        ids = [f"{doc_id}-chunk-{i}" for i in range(len(chunks))]

        count = await vector_store_service.add_documents(
            texts=texts,
            metadatas=metadatas,
            ids=ids,
            collection=collection,
        )

        return (
            f"Successfully ingested {count} chunks from '{path.name}' "
            f"into collection '{collection}'."
        )
    except Exception as exc:
        return f"Ingestion error: {exc}"


@rag_mcp.tool()
async def list_collections() -> str:
    """List all vector store collections with document counts."""
    from app.services.vector_store import vector_store_service

    try:
        collections = await vector_store_service.list_collections()
        if not collections:
            return "No collections found in the vector store."
        return json.dumps(collections, indent=2)
    except Exception as exc:
        return f"Error listing collections: {exc}"


@rag_mcp.tool()
async def delete_collection(name: str) -> str:
    """Delete a vector store collection and all its data.

    Args:
        name: The name of the collection to delete.
    """
    from app.services.vector_store import vector_store_service

    try:
        deleted = await vector_store_service.delete_collection(name)
        if deleted:
            return f"Collection '{name}' deleted successfully."
        return f"Collection '{name}' not found."
    except Exception as exc:
        return f"Error deleting collection: {exc}"


@rag_mcp.resource("collections://{name}/stats")
async def collection_stats(name: str) -> str:
    """Get statistics for a specific collection.

    Args:
        name: The collection name.
    """
    from app.services.vector_store import vector_store_service

    try:
        count = await vector_store_service.get_collection_count(name)
        return json.dumps({"name": name, "document_count": count}, indent=2)
    except Exception as exc:
        return f"Error getting stats: {exc}"


if __name__ == "__main__":
    rag_mcp.run()
