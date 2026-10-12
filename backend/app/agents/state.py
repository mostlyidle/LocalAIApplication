"""Shared agent state schema for LangGraph.

All agents operate on this shared state, which flows through the LangGraph
graph. Uses TypedDict for LangGraph compatibility.
"""

from __future__ import annotations

from typing import Annotated, Any, NotRequired

from langchain_core.messages import AnyMessage  # noqa: TC002
from langgraph.graph import add_messages
from typing_extensions import TypedDict


class AgentState(TypedDict):
    """Shared state passed through the LangGraph agent graph.

    Attributes:
        messages: The conversation history (LangChain message objects).
            Uses `add_messages` reducer to properly append new messages.
        current_agent: The name of the currently active agent.
        next_agent: The agent to route to next (set by orchestrator).
        user_input: The original user message text.
        attachments: File paths or URLs attached to the message.
        conversation_id: ID of the current conversation for persistence.
        tool_calls: Record of tool calls made during this turn.
        metadata: Arbitrary metadata (tokens used, timing, etc.).
        error: Error message if something went wrong.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    current_agent: str
    next_agent: str | None
    user_input: str
    attachments: list[str]
    conversation_id: str
    tool_calls: list[dict[str, Any]]
    metadata: dict[str, Any]
    error: str | None
    database: NotRequired[str]
    forced_agent: NotRequired[str]
    owner_id: NotRequired[str]
    memory_context: NotRequired[str]


def create_initial_state(
    user_input: str,
    conversation_id: str,
    attachments: list[str] | None = None,
    owner_id: str | None = None,
) -> AgentState:
    """Create a fresh AgentState for a new user message.

    Args:
        user_input: The user's message text.
        conversation_id: The conversation ID.
        attachments: Optional file paths or URLs.

    Returns:
        An initialized AgentState.
    """
    state = AgentState(
        messages=[],
        current_agent="orchestrator",
        next_agent=None,
        user_input=user_input,
        attachments=attachments or [],
        conversation_id=conversation_id,
        tool_calls=[],
        metadata={},
        error=None,
    )
    if owner_id is not None:
        state["owner_id"] = owner_id
    return state
