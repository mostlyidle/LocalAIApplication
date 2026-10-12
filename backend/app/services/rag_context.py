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
    memory_context: str = ""


async def prepare_rag_context(
    request: TaskRequest,
    execution: AgentExecution,
    prompts: PromptStore,
    *,
    history: list[str] | None = None,
    owner_id: str | None = None,
    memory_context: str = "",
) -> RagContext:
    """Retrieve first and include only complete passages that fit the answer budget."""
    from app.services.hybrid_vector_store import hybrid_vector_store_service

    if owner_id is not None:
        from app.services.database import get_app_session_factory
        from app.services.rag_access import collection_access

        factory = get_app_session_factory()
        async with factory() as db:
            access = await collection_access(
                db,
                hybrid_vector_store_service,
                name=request.collection,
                owner_id=owner_id,
            )
        if access in {"foreign", "unassigned"}:
            raise HTTPException(status_code=404, detail="RAG collection was not found.")

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
    selected_memory = memory_context

    def memory_size() -> int:
        if not selected_memory:
            return 0
        from app.agents.memory_context import MEMORY_CONTEXT_INSTRUCTIONS

        return len(f"{MEMORY_CONTEXT_INSTRUCTIONS}\n{selected_memory}".encode())

    def fits() -> bool:
        system, user = prompts.render_messages(execution.profile.name, "rag", context.prompt_values)
        # shortcut: UTF-8 bytes conservatively bound text tokens; use model tokenization when available.
        return len(system.encode("utf-8")) + len(user.encode("utf-8")) + memory_size() <= budget

    if not fits():
        if selected_memory:
            selected_memory = ""
            context.limitations.append(
                "Personal memory was omitted to preserve the RAG question and document evidence budget."
            )
        if fits():
            pass
        else:
            raise HTTPException(
                status_code=422,
                detail="The question and output allowance exceed the RAG context budget. Increase the context window or shorten the question/output limit.",
            )
    def fit_passages() -> list[str]:
        context.prompt_values["passages"] = ""
        context.citations.clear()
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
        return rows

    rows = fit_passages()
    if not context.citations and selected_memory:
        selected_memory = ""
        context.limitations.append(
            "Personal memory was omitted to preserve room for a complete document passage."
        )
        rows = fit_passages()
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
    context.memory_context = selected_memory
    return context
