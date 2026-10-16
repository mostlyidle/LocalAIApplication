"""LangGraph Orchestrator — supervisor/router for the multi-agent system.

Receives user input, classifies intent via a lightweight LLM call,
and routes to the appropriate specialist agent. The compiled graph
supports streaming via ``astream_events`` for real-time UI updates.

Design decisions:
    - Uses a dedicated LLM call (low temperature, constrained output) for
      intent classification rather than keyword heuristics, so it can handle
      ambiguous or multi-domain queries.
    - Each agent is a standalone LangGraph node; the router is a conditional
      edge that reads ``next_agent`` from state.
    - Fallback to the chat agent on classification failure ensures the user
      always receives a response.
    - The graph is compiled once at module level (``orchestrator_graph``) and
      reused across requests.
"""

from __future__ import annotations

from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, ValidationError

from app.agents.chat_agent import chat_agent_node
from app.agents.document_agent import document_agent_node
from app.agents.rag_agent import rag_agent_node
from app.agents.sql_agent import sql_agent_node
from app.agents.state import AgentState
from app.agents.web_agent import web_agent_node
from app.models.enums import AgentType
from app.services.llm import llm_service

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------

ROUTER_SYSTEM_PROMPT = """You are an intent classifier for a local AI application. Your ONLY job is to classify the user's message into exactly one category.

Categories:
- "sql" — The user wants to query a database, inspect schemas, write SQL, or analyze tabular data stored in a database.
- "document" — The user wants to parse, analyze, extract text/tables from an uploaded file (PDF, DOCX, image, etc.), or asks about attached files.
- "rag" — The user wants to search a knowledge base, find information across previously ingested documents, or asks you to remember/recall stored content.
- "web" — The user wants to search for current information, answer a recent-events question, or fetch, read, or summarize website content.
- "chat" — General conversation, greetings, coding help, math, knowledge questions, or anything that doesn't fit the above categories.

Rules:
1. Respond with ONLY a JSON object: {"agent": "<category>"}
2. If the message mentions attachments or file paths AND asks to analyze them, choose "document".
3. If the message mentions a URL (http/https), choose "web".
4. If the user asks for recent or current facts that need outside sources, choose "web" even without a URL.
5. If the message asks to search or query "the knowledge base", "documents", or "ingested files", choose "rag".
6. If the message mentions database, SQL, tables (in a DB context), queries, or schema, choose "sql".
7. When in doubt, choose "chat".
8. Do NOT add any explanation — ONLY the JSON object."""

VALID_AGENTS = {member.value for member in AgentType}


class RouterDecision(BaseModel):
    """Schema enforced by local Ollama for intent routing."""

    agent: AgentType


async def classify_intent(state: AgentState) -> dict[str, Any]:
    """Classify the user's intent and set ``next_agent`` in state.

    Uses a fast, low-temperature LLM call with a constrained system prompt
    to decide which specialist agent should handle the message. Falls back
    to the chat agent if classification fails.

    Args:
        state: The current agent state.

    Returns:
        State update with ``next_agent`` set.
    """
    user_input = state.get("user_input", "")
    attachments = state.get("attachments", [])
    forced_agent = state.get("forced_agent")
    if forced_agent in VALID_AGENTS:
        return {"next_agent": forced_agent, "current_agent": "orchestrator"}

    logger.info(
        "classifying_intent",
        conversation_id=state.get("conversation_id"),
        input_length=len(user_input),
        attachment_count=len(attachments),
    )

    # Quick heuristic pre-check for obvious cases — avoids an LLM call
    chosen_agent = _heuristic_classify(user_input, attachments)
    if chosen_agent is not None:
        logger.info("intent_classified_heuristic", agent=chosen_agent)
        return {
            "next_agent": chosen_agent,
            "current_agent": "orchestrator",
        }

    # LLM-based classification
    llm = llm_service.get_chat_model(
        temperature=0.0,
        max_tokens=64,
        format=RouterDecision.model_json_schema(),
    )

    classification_messages = [
        SystemMessage(content=ROUTER_SYSTEM_PROMPT),
        HumanMessage(content=_build_classification_input(user_input, attachments)),
    ]

    try:
        response = await llm.ainvoke(classification_messages)
        content = response.content.strip() if response.content else ""
        chosen_agent = _parse_classification(content)
    except Exception as exc:
        logger.warning("intent_classification_failed", error=str(exc))
        chosen_agent = AgentType.CHAT

    logger.info("intent_classified", agent=chosen_agent)

    return {
        "next_agent": chosen_agent,
        "current_agent": "orchestrator",
    }


def _build_classification_input(user_input: str, attachments: list[str]) -> str:
    """Build the message sent to the classifier LLM.

    Includes attachment info so the classifier can account for files.
    """
    text = user_input
    if attachments:
        files = ", ".join(attachments)
        text += f"\n\n[Attached files: {files}]"
    return text


def _heuristic_classify(
    user_input: str,
    attachments: list[str],
) -> str | None:
    """Fast keyword-based classification for obvious cases.

    Returns an agent name string or ``None`` if uncertain.
    """
    lower = user_input.lower()

    # URLs are a strong signal for web agent
    if "http://" in lower or "https://" in lower:
        return AgentType.WEB

    # Attachments present + action words -> document agent
    if attachments:
        doc_words = {"parse", "extract", "ocr", "analyze", "read", "scan", "table"}
        if any(w in lower for w in doc_words):
            return AgentType.DOCUMENT

    # Explicit SQL / database keywords
    sql_keywords = {"select ", "sql ", "database", "query the", "schema", " table ", "join "}
    if any(kw in lower for kw in sql_keywords):
        return AgentType.SQL

    # Explicit RAG / knowledge base keywords
    rag_keywords = {"knowledge base", "ingested", "search documents", "vector search", "rag "}
    if any(kw in lower for kw in rag_keywords):
        return AgentType.RAG

    return None


def _parse_classification(content: str) -> str:
    """Validate schema-constrained routing JSON and fall back to chat on invalid output."""
    try:
        return RouterDecision.model_validate_json(content).agent
    except ValidationError:
        logger.warning("unparseable_classification")
        return AgentType.CHAT


# ---------------------------------------------------------------------------
# LangGraph routing logic
# ---------------------------------------------------------------------------


def route_to_agent(state: AgentState) -> str:
    """Conditional edge function: route to the selected agent node.

    Reads ``next_agent`` from state (set by the classifier) and maps
    it to the corresponding LangGraph node name.

    Args:
        state: The current agent state.

    Returns:
        Node name to transition to.
    """
    next_agent = state.get("next_agent", AgentType.CHAT)
    if next_agent not in VALID_AGENTS:
        logger.warning("invalid_next_agent", agent=next_agent)
        return AgentType.CHAT
    return next_agent


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def build_orchestrator_graph() -> StateGraph:
    """Construct the LangGraph StateGraph for the multi-agent orchestrator.

    Graph topology::

        START -> classify_intent -> (conditional) -> [chat | sql | document | rag | web] -> END

    Returns:
        A compiled LangGraph graph ready for ``ainvoke`` / ``astream_events``.
    """
    graph = StateGraph(AgentState)

    # -- Nodes --
    graph.add_node("classify_intent", classify_intent)
    graph.add_node(AgentType.CHAT, chat_agent_node)
    graph.add_node(AgentType.SQL, sql_agent_node)
    graph.add_node(AgentType.DOCUMENT, document_agent_node)
    graph.add_node(AgentType.RAG, rag_agent_node)
    graph.add_node(AgentType.WEB, web_agent_node)

    # -- Edges --
    graph.set_entry_point("classify_intent")

    graph.add_conditional_edges(
        "classify_intent",
        route_to_agent,
        {
            AgentType.CHAT: AgentType.CHAT,
            AgentType.SQL: AgentType.SQL,
            AgentType.DOCUMENT: AgentType.DOCUMENT,
            AgentType.RAG: AgentType.RAG,
            AgentType.WEB: AgentType.WEB,
        },
    )

    # All agent nodes terminate after execution
    graph.add_edge(AgentType.CHAT, END)
    graph.add_edge(AgentType.SQL, END)
    graph.add_edge(AgentType.DOCUMENT, END)
    graph.add_edge(AgentType.RAG, END)
    graph.add_edge(AgentType.WEB, END)

    return graph.compile()


# Module-level compiled graph — import and reuse across the application.
orchestrator_graph = build_orchestrator_graph()


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------


async def run_agent(
    user_input: str,
    conversation_id: str,
    attachments: list[str] | None = None,
    existing_messages: list | None = None,
    forced_agent: str | None = None,
    owner_id: str | None = None,
    system_prompts: dict[str, str] | None = None,
) -> AgentState:
    """Run the full orchestrator pipeline for a user message.

    This is the primary entry point used by API routes. It creates the
    initial state, invokes the compiled graph, and returns the final state.

    Args:
        user_input: The user's message text.
        conversation_id: The conversation ID for persistence.
        attachments: Optional file paths or URLs.
        existing_messages: Optional prior conversation messages to prepend.

    Returns:
        The final AgentState after the graph completes.
    """
    from app.agents.state import create_initial_state

    state = create_initial_state(
        user_input=user_input,
        conversation_id=conversation_id,
        attachments=attachments,
        owner_id=owner_id,
    )
    if owner_id:
        from app.services.memory_context import load_account_memory_context

        state["memory_context"] = await load_account_memory_context(
            owner_id,
            query=user_input,
            exclude_conversation_id=conversation_id,
        )
    if forced_agent:
        state["forced_agent"] = forced_agent
    if system_prompts is not None:
        state["system_prompts"] = system_prompts
    # Inject conversation history if provided
    if existing_messages:
        state["messages"] = list(existing_messages)
    state["messages"].append(
        HumanMessage(content=_build_classification_input(user_input, attachments or []))
    )

    result = await orchestrator_graph.ainvoke(state)
    return result


async def stream_agent(
    user_input: str,
    conversation_id: str,
    attachments: list[str] | None = None,
    existing_messages: list | None = None,
    forced_agent: str | None = None,
    owner_id: str | None = None,
    system_prompts: dict[str, str] | None = None,
):
    """Stream events from the orchestrator graph for real-time UI updates.

    Yields LangGraph events suitable for WebSocket streaming. Each event
    contains type and data fields matching the StreamEventType protocol.

    Args:
        user_input: The user's message text.
        conversation_id: The conversation ID for persistence.
        attachments: Optional file paths or URLs.
        existing_messages: Optional prior conversation messages to prepend.

    Yields:
        Dicts with streaming event data (tokens, tool calls, agent switches, etc.).
    """
    from app.agents.state import create_initial_state

    state = create_initial_state(
        user_input=user_input,
        conversation_id=conversation_id,
        attachments=attachments,
        owner_id=owner_id,
    )
    if owner_id:
        from app.services.memory_context import load_account_memory_context

        state["memory_context"] = await load_account_memory_context(
            owner_id,
            query=user_input,
            exclude_conversation_id=conversation_id,
        )
    if forced_agent:
        state["forced_agent"] = forced_agent
    if system_prompts is not None:
        state["system_prompts"] = system_prompts
    if existing_messages:
        state["messages"] = list(existing_messages)
    state["messages"].append(
        HumanMessage(content=_build_classification_input(user_input, attachments or []))
    )

    answer_emitted = False
    async for event in orchestrator_graph.astream_events(state, version="v2"):
        kind = event.get("event", "")
        data = event.get("data", {})

        # Emit agent switch events
        if kind == "on_chain_start" and event.get("name") in VALID_AGENTS:
            yield {
                "type": "agent_switch",
                "agent": event["name"],
            }

        # Emit individual tokens from LLM streaming
        if (
            kind == "on_chat_model_stream"
            and event.get("metadata", {}).get("langgraph_node") != "classify_intent"
        ):
            chunk = data.get("chunk")
            if chunk and hasattr(chunk, "content") and chunk.content:
                answer_emitted = True
                yield {
                    "type": "token",
                    "content": str(chunk.content),
                }

        # Emit tool call starts
        if kind == "on_tool_start":
            yield {
                "type": "tool_call",
                "tool": event.get("name", "unknown"),
                "input": data.get("input", {}),
            }

        # Emit tool results
        if kind == "on_tool_end":
            output = data.get("output", "")
            yield {
                "type": "tool_result",
                "tool": event.get("name", "unknown"),
                "output": str(output)[:2000],
            }

        # Emit completion
        if kind == "on_chain_end" and event.get("name") == "LangGraph":
            final_state = data.get("output", {})
            if not answer_emitted:
                messages = final_state.get("messages", [])
                if (
                    messages
                    and getattr(messages[-1], "type", None) == "ai"
                    and messages[-1].content
                ):
                    yield {"type": "token", "content": str(messages[-1].content)}
            yield {
                "type": "done",
                "metadata": final_state.get("metadata", {}),
                "state": final_state,
            }
