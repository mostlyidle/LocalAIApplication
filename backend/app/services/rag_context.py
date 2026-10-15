"""Shared retrieval and context budgeting for task and conversational RAG."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from time import perf_counter
from typing import TYPE_CHECKING

from fastapi import HTTPException

from app.config import settings

if TYPE_CHECKING:
    from app.agents.registry import AgentExecution, AgentManifest
    from app.models.profile_schemas import TaskRequest
    from app.prompt_store import PromptStore


@dataclass
class RagContext:
    prompt_values: dict[str, object]
    citations: list[dict[str, object]]
    retrieval: dict[str, object]
    limitations: list[str] = field(default_factory=list)
    memory_context: str = ""
    answer_override: str | None = None


async def prepare_rag_context(
    request: TaskRequest,
    execution: AgentExecution,
    prompts: PromptStore,
    *,
    history: list[str] | None = None,
    owner_id: str | None = None,
    memory_context: str = "",
    system_prompt: str | None = None,
    _bypass_laya_rewrite: bool = False,
    _skip_laya_evidence: bool = False,
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
            _bypass_laya_rewrite=_bypass_laya_rewrite,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    context = RagContext(
        prompt_values={"prompt": request.prompt, "passages": "", "history": ""},
        citations=[], retrieval=dict(search.retrieval),
    )
    if not search.passages:
        context.limitations.append("No supporting passages were retrieved.")
        _record_evidence_metadata(
            context,
            {
                "mode": settings.laya_rag_evidence_mode,
                "outcome": "not_run",
                "reason": "no_evidence",
                "choice": None,
                "probability": None,
                "schema_version": "evidence-v1",
                "model_digest": None,
                "elapsed_ms": 0,
                "evidence_bytes": 0,
                "coverage": {
                    "submitted_complete": False,
                    "tokenizer_server_parity_verified": False,
                },
                "would_apply": False,
                "applied": False,
                "answer_generation_avoided": False,
            },
        )
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
        if system_prompt is not None:
            system = system_prompt
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
    if not _skip_laya_evidence:
        laya_context = await _check_laya_evidence(
            context,
            request,
            execution,
            prompts,
            history_text=context.prompt_values["history"],
            memory_context=selected_memory,
            system_prompt=system_prompt,
            owner_id=owner_id,
            history=history,
        )
        if laya_context is not None:
            return laya_context
    return context


async def _check_laya_evidence(
    context: RagContext,
    request: TaskRequest,
    execution: AgentExecution,
    prompts: PromptStore,
    *,
    history_text: str,
    memory_context: str,
    system_prompt: str | None,
    owner_id: str | None,
    history: list[str] | None,
) -> RagContext | None:
    """Apply a calibrated unsupported verdict only to complete final evidence."""
    from app.services.hybrid_vector_store import hybrid_vector_store_service

    profile = execution.profile
    mode = settings.laya_rag_evidence_mode
    metadata: dict[str, object] = {
        "mode": mode,
        "outcome": "not_run",
        "reason": "off" if mode == "off" else "not_ready",
        "choice": None,
        "probability": None,
        "schema_version": "evidence-v1",
        "model_digest": None,
        "elapsed_ms": 0,
        "evidence_bytes": len(str(context.prompt_values["passages"]).encode("utf-8")),
        "coverage": {
            "submitted_complete": False,
            "tokenizer_server_parity_verified": False,
        },
        "would_apply": False,
        "applied": False,
        "answer_generation_avoided": False,
    }
    if mode == "off":
        _record_evidence_metadata(context, metadata)
        return

    context_reason = _evidence_context_reason(
        request.prompt,
        has_history=bool(history_text),
        has_memory=bool(memory_context),
    )
    laya = hybrid_vector_store_service.laya_service
    if context_reason is not None:
        metadata["reason"] = context_reason
        _record_evidence_metadata(context, metadata)
        return
    if laya is None:
        _record_evidence_metadata(context, metadata)
        return

    evidence_text = str(context.prompt_values["passages"])
    decision = await laya.check_evidence(request.prompt, [evidence_text])
    eligible, policy_reason = laya.can_apply(
        "evidence",
        profile=profile.name,
        prompt_digest=_evidence_configuration_digest(profile, prompts, system_prompt),
        decision=decision,
        input_covered=True,
        context_independent=True,
    )
    applied = mode == "enforce" and eligible
    metadata.update(
        outcome=decision.choice or "abstained",
        reason=policy_reason,
        choice=decision.choice,
        probability=decision.probability,
        schema_version=decision.schema_version,
        model_digest=laya.model_digest,
        elapsed_ms=decision.elapsed_ms,
        input_bytes=getattr(decision, "input_bytes", 0),
        coverage={
            "submitted_complete": decision.reason == "evaluated",
            "tokenizer_server_parity_verified": getattr(
                laya, "tokenizer_server_parity_verified", False
            ),
        },
        would_apply=eligible,
        applied=applied,
        answer_generation_avoided=applied,
    )
    if not applied:
        _record_evidence_metadata(context, metadata)
        return

    candidate_citations = [dict(citation) for citation in context.citations]
    metadata["candidate_citations"] = candidate_citations
    rewrite_was_skipped = bool(context.retrieval.get("skipped_by_laya"))
    if rewrite_was_skipped:
        rescue_started = perf_counter()
        rescued = await prepare_rag_context(
            request,
            execution,
            prompts,
            history=history,
            owner_id=owner_id,
            memory_context=memory_context,
            system_prompt=system_prompt,
            _bypass_laya_rewrite=True,
            _skip_laya_evidence=True,
        )
        metadata["rescue"] = {
            "triggered": True,
            "elapsed_ms": (perf_counter() - rescue_started) * 1000,
            "passages": len(rescued.citations),
            "retrieval_mode": rescued.retrieval.get("mode"),
        }
        metadata["answer_generation_avoided"] = False
        _record_evidence_metadata(rescued, metadata)
        return rescued

    context.answer_override = (
        "I couldn't find enough supporting evidence in the retrieved passages to answer this question."
    )
    context.citations.clear()
    context.memory_context = ""
    context.limitations.append(
        "The retrieved passages did not provide enough evidence for an answer."
    )
    _record_evidence_metadata(context, metadata)


def _evidence_context_reason(
    question: str,
    *,
    has_history: bool,
    has_memory: bool,
) -> str | None:
    if has_history or has_memory:
        return "context_dependent"
    if len(question.encode("utf-8")) > 512:
        return "budget_exceeded"
    if not question.isascii():
        return "unsupported_language"
    if re.search(
        r"\b(?:it|this|that|they|them|those|these|same|former|latter|the first|the second)\b",
        question.casefold(),
    ):
        return "context_dependent"
    return None


def _evidence_configuration_digest(
    profile: AgentManifest,
    prompts: PromptStore,
    system_prompt: str | None,
) -> str:
    """Fingerprint the RAG profile and effective answer prompt templates."""
    system, user = prompts.render_messages(
        profile.name,
        "rag",
        {"prompt": "__QUESTION__", "passages": "__EVIDENCE__", "history": "__HISTORY__"},
    )
    if system_prompt is not None:
        system = system_prompt
    material = {
        "profile": profile.model_dump(mode="json"),
        "system": system,
        "user": user,
    }
    serialized = json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _record_evidence_metadata(context: RagContext, metadata: dict[str, object]) -> None:
    laya_metadata = context.retrieval.get("laya")
    if not isinstance(laya_metadata, dict):
        laya_metadata = {}
        context.retrieval["laya"] = laya_metadata
    laya_metadata["evidence"] = metadata
