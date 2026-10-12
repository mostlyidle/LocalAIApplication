"""Shared retrieval and context budgeting for task and conversational RAG."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fastapi import HTTPException

from app.config import settings

if TYPE_CHECKING:
    from app.agents.registry import AgentExecution
    from app.models.profile_schemas import TaskRequest
    from app.prompt_store import PromptStore


@dataclass
class RagContext:
    prompt_values: dict[str, object]
    citations: list[dict[str, object]]
    retrieval: dict[str, object]
    limitations: list[str] = field(default_factory=list)


async def prepare_rag_context(
    request: TaskRequest,
    execution: AgentExecution,
    prompts: PromptStore,
    *,
    history: list[str] | None = None,
) -> RagContext:
    """Retrieve first and include only complete passages that fit the answer budget."""
    from app.services.hybrid_vector_store import hybrid_vector_store_service

    inference = execution.inference
    assert inference is not None
    try:
        search = await hybrid_vector_store_service.search_with_provenance(
            query=request.prompt,
            collection=request.collection,
            top_k=settings.rag_top_k,
            agent_name=execution.profile.name,
            rewrite_model=inference.model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    context = RagContext(
        prompt_values={"prompt": request.prompt, "passages": "", "history": ""},
        citations=[], retrieval=dict(search.retrieval),
    )
    if not search.passages:
        context.limitations.append("No supporting passages were retrieved.")
        return context
    if search.retrieval.get("recorded_identity_only"):
        context.limitations.append(
            "This older collection records a model and revision, but no weight digest. "
            "Search is read-only; re-embed into a new collection to verify the embedding identity."
        )
    budget = min(int(inference.context_window * 0.7), inference.context_window - inference.max_output_tokens) - 64

    def fits() -> bool:
        system, user = prompts.render_messages(execution.profile.name, "rag", context.prompt_values)
        # shortcut: UTF-8 bytes conservatively bound text tokens; use model tokenization when available.
        return len(system.encode("utf-8")) + len(user.encode("utf-8")) <= budget

    if not fits():
        raise HTTPException(
            status_code=422,
            detail="The question and output allowance exceed the RAG context budget. Increase the context window or shorten the question/output limit.",
        )
    rows: list[str] = []
    for passage in search.passages:
        metadata = passage.get("metadata", {})
        citation = {
            key: metadata[key]
            for key in ("filename", "source", "page", "page_start", "page_end", "section", "document_id", "source_chunk_id")
            if metadata.get(key) is not None
        }
        citation.update(
            asset_id=metadata.get("asset_id", passage.get("asset_id")),
            chunk_index=metadata.get("chunk_index", passage.get("chunk_index")),
            score=passage.get("score"), score_type=passage.get("score_type"),
        )
        source = citation.get("filename") or citation.get("source") or citation.get("document_id") or "Unknown"
        location = f", Page {citation['page']}" if citation.get("page") is not None else ""
        section = f", Section {citation['section']}" if citation.get("section") else ""
        row = f"[{citation['asset_id']}:{citation['chunk_index']}] [Source: {source}{location}{section}]\n{passage.get('content', '')}"
        context.prompt_values["passages"] = "\n\n".join([*rows, row])
        if fits():
            rows.append(row)
            context.citations.append(citation)
        else:
            context.prompt_values["passages"] = "\n\n".join(rows)
    if not context.citations:
        raise HTTPException(
            status_code=422,
            detail="No complete retrieved passage fits this context window. Increase the RAG context window.",
        )
    turns: list[str] = []
    for turn in reversed((history or [])[-8:]):
        context.prompt_values["history"] = "\n".join([turn, *turns])
        if fits():
            turns.insert(0, turn)
        else:
            context.prompt_values["history"] = "\n".join(turns)
    if len(rows) < len(search.passages) or len(turns) < len(history or []):
        context.limitations.append("Some retrieved passages or prior turns were omitted to fit the selected context window.")
    return context
