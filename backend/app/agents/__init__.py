"""Agents package — LangGraph multi-agent orchestrator and specialist agents.

Public API:
    orchestrator_graph  — Compiled LangGraph StateGraph (invoke / stream).
    run_agent           — Convenience wrapper: classify + route + execute.
    stream_agent        — Streaming wrapper for WebSocket delivery.
    create_initial_state — Build an initial AgentState for a new turn.

    Individual agent nodes (for testing or direct invocation):
        chat_agent_node, sql_agent_node, document_agent_node,
        rag_agent_node, web_agent_node, classify_intent.
"""

from app.agents.chat_agent import chat_agent_node, chat_agent_stream
from app.agents.document_agent import document_agent_node
from app.agents.orchestrator import (
    classify_intent,
    orchestrator_graph,
    run_agent,
    stream_agent,
)
from app.agents.rag_agent import rag_agent_node
from app.agents.sql_agent import sql_agent_node
from app.agents.state import AgentState, create_initial_state
from app.agents.web_agent import web_agent_node

__all__ = [
    "AgentState",
    "chat_agent_node",
    "chat_agent_stream",
    "classify_intent",
    "create_initial_state",
    "document_agent_node",
    "orchestrator_graph",
    "rag_agent_node",
    "run_agent",
    "sql_agent_node",
    "stream_agent",
    "web_agent_node",
]
