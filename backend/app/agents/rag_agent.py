"""Conversational RAG using the shared retrieve-before-generation pipeline."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.memory_context import MEMORY_CONTEXT_INSTRUCTIONS
from app.agents.registry import AgentExecution
from app.config import settings
from app.models.profile_schemas import AgentResult, ExecutionMetadata, TaskRequest
from app.prompt_store import PromptStore
from app.services.hybrid_vector_store import hybrid_vector_store_service
from app.services.llm import llm_service
from app.services.memory_context import memory_sources_from_context
from app.services.rag_context import prepare_rag_context

if TYPE_CHECKING:
    from app.agents.state import AgentState


async def rag_agent_node(state: AgentState) -> dict[str, Any]:
    """Retrieve complete cited evidence before making one answer-model call."""
    registry = hybrid_vector_store_service.profile_registry()
    profile = registry.default_for("rag")
    # Automatic routing retains the configured chat model; explicit profiles use their allowlist.
    inference = profile.inference.defaults.model_copy(update={"model": settings.ollama_chat_model})
    execution = AgentExecution(profile, inference)
    prompts = PromptStore(Path(__file__).parents[1] / "prompts")
    request = TaskRequest(prompt=state["user_input"], agent_name=profile.name, collection=settings.chroma_collection_name)
    history = [
        f"{message.type}: {str(message.content)[:1200]}"
        for message in state["messages"][:-1][-8:]
        if getattr(message, "content", None)
    ]
    context = await prepare_rag_context(
        request,
        execution,
        prompts,
        history=history,
        owner_id=state.get("owner_id"),
        memory_context=state.get("memory_context", ""),
    )
    if context.citations:
        system, user = prompts.render_messages(profile.name, "rag", context.prompt_values)
        system = state.get("system_prompts", {}).get("rag", system)
        messages = [SystemMessage(content=system)]
        if context.memory_context:
            messages.append(
                SystemMessage(
                    content=f"{MEMORY_CONTEXT_INSTRUCTIONS}\n{context.memory_context}"
                )
            )
        messages.append(HumanMessage(content=user))
        with llm_service.inference_context(inference):
            model = llm_service.get_chat_model()
            response = await model.ainvoke(messages)
    else:
        context.memory_context = ""
        response = AIMessage(content="I could not find relevant evidence in the selected collection.")
    artifacts = {
        "citations": context.citations,
        "retrieval": context.retrieval,
        "memory_sources": memory_sources_from_context(context.memory_context),
    }
    result = AgentResult(
        agent=profile.name, answer=str(response.content),
        artifacts=artifacts,
        limitations=context.limitations,
        metadata=ExecutionMetadata(request_id=str(uuid.uuid4()), target="rag", agent_name=profile.name, model=inference.model, inference=inference),
    )
    return {
        "messages": [response],
        "current_agent": "rag",
        "memory_context": context.memory_context,
        "metadata": {**state.get("metadata", {}), "agent_used": "rag", "retrieval": context.retrieval, "execution": result.model_dump(mode="json")},
    }
