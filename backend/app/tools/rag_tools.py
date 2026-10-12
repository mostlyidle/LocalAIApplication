"""RAG tools for embedding, searching, and retrieving documents from the vector store.

These tools interface with Qdrant via the hybrid vector-store service and handle
the complete RAG pipeline: ingest (chunk + embed + store) and search.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import structlog
from langchain_core.tools import tool

from app.config import settings
from app.services.document_parser import document_parser_service
from app.services.hybrid_vector_store import hybrid_vector_store_service as vector_store_service
from app.tools.document_tools import parse_document_file

logger = structlog.get_logger(__name__)


async def ingest_document(
    file_path: Path,
    collection: str | None = None,
    document_id: str | None = None,
) -> dict[str, Any]:
    """Ingest a document into the vector store.

    Pipeline: parse -> chunk -> embed -> store in Qdrant.

    Args:
        file_path: Path to the document file.
        collection: Target collection name (default: settings.chroma_collection_name).
        document_id: Optional ID for the document (auto-generated if not provided).

    Returns:
        Dict with document_id, chunk_count, and collection name.
    """
    doc_id = document_id or str(uuid.uuid4())
    parsed = await parse_document_file(file_path)

    # Chunk the text
    chunks = document_parser_service.chunk_document(
        parsed,
        metadata={
            "source": file_path.name,
            "document_id": doc_id,
            "format": parsed.metadata.get("format", "unknown"),
        },
    )

    if not chunks:
        logger.warning("no_chunks_generated", file=file_path.name)
        return {"document_id": doc_id, "chunk_count": 0, "collection": collection}

    texts = [c["text"] for c in chunks]
    metadatas = [c["metadata"] for c in chunks]
    ids = [f"{doc_id}_{i}" for i in range(len(chunks))]

    count = await vector_store_service.add_documents(
        texts=texts,
        metadatas=metadatas,
        ids=ids,
        collection=collection,
    )

    logger.info(
        "document_ingested",
        document_id=doc_id,
        chunks=count,
        collection=collection or settings.chroma_collection_name,
    )
    return {
        "document_id": doc_id,
        "chunk_count": count,
        "collection": collection or settings.chroma_collection_name,
    }


async def search_documents(
    query: str,
    collection: str | None = None,
    top_k: int | None = None,
    score_threshold: float | None = None,
    agent_name: str = "rag",
) -> list[dict[str, Any]]:
    """Search the vector store for relevant document chunks.

    Args:
        query: Natural language search query.
        collection: Target collection (default from settings).
        top_k: Max results to return.
        score_threshold: Minimum similarity score.

    Returns:
        List of result dicts with content, score, and metadata.
    """
    return await vector_store_service.search(
        query=query,
        collection=collection,
        top_k=top_k,
        score_threshold=score_threshold,
        agent_name=agent_name,
    )


# ── LangChain tool wrappers ────────────────────────────────────────────


@tool
async def rag_search_tool(
    query: str,
    collection: str = "documents",
    top_k: int = 5,
    agent_name: str = "rag",
) -> str:
    """Search the document knowledge base for relevant information.

    Use this tool when you need to find information from previously
    ingested documents. Returns the most relevant text chunks with
    source citations.

    Args:
        query: Natural language search query describing what you're looking for.
        collection: The document collection to search (default: "documents").
        top_k: Maximum number of results to return (default: 5).

    Returns:
        Relevant document excerpts with source citations and relevance scores.
    """
    results = await search_documents(
        query=query,
        collection=collection,
        top_k=top_k,
        agent_name=agent_name,
    )

    if not results:
        return "No relevant documents found for your query."

    parts = []
    for i, r in enumerate(results, 1):
        source = r.get("metadata", {}).get("source", "Unknown")
        score = r.get("score", 0)
        score_type = r.get("score_type", "unknown")
        page = r.get("metadata", {}).get("page")
        content = r["content"][:500]  # Cap per-chunk display

        citation = f"[Source: {source}"
        if page:
            citation += f", Page {page}"
        citation += f", {score_type.upper()} score: {score:.4f}]"

        parts.append(f"Result {i} {citation}:\n{content}")

    return "\n\n---\n\n".join(parts)


@tool
async def rag_ingest_tool(
    file_path: str,
    collection: str = "documents",
) -> str:
    """Ingest a document into the knowledge base for future retrieval.

    The document is parsed, split into chunks, embedded, and stored
    in the vector database.

    Args:
        file_path: Absolute path to the document file to ingest.
        collection: Target collection name (default: "documents").

    Returns:
        Summary of the ingestion (document ID, chunk count).
    """
    path = Path(file_path)
    result = await ingest_document(path, collection=collection)
    return (
        f"Document ingested successfully.\n"
        f"Document ID: {result['document_id']}\n"
        f"Chunks created: {result['chunk_count']}\n"
        f"Collection: {result['collection']}"
    )


@tool
async def rag_list_collections_tool() -> str:
    """List all document collections in the knowledge base.

    Returns:
        Collection names with document counts.
    """
    collections = await vector_store_service.list_collections()
    if not collections:
        return "No collections found in the knowledge base."

    lines = ["Collections:"]
    for col in collections:
        lines.append(f"  - {col['name']}: {col['document_count']} documents")
    return "\n".join(lines)


# All RAG tools for agent binding
rag_tools = [rag_search_tool, rag_ingest_tool, rag_list_collections_tool]
