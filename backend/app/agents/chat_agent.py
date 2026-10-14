"""General conversational chat agent.

Handles general-purpose conversation, small talk, and queries that don't
require specialist agents. Uses the base chat model with no tools bound.
"""

from __future__ import annotations

from typing import Any

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.memory_context import memory_context_message
from app.agents.state import AgentState
from app.services.llm import llm_service

logger = structlog.get_logger(__name__)

CHAT_SYSTEM_PROMPT = """You are a helpful, knowledgeable AI assistant running locally on the user's Mac. You are powered by Ollama and open-source language models.

Key traits:
- You are direct, concise, and accurate.
- You acknowledge when you don't know something rather than guessing.
- You can help with general knowledge, writing, coding, analysis, and conversation.
- You are running 100% locally — no data leaves the user's machine.

If the user asks about documents, databases, or web content, let them know you can help with those tasks through specialized tools. But for now, just have a natural conversation."""


async def chat_agent_node(state: AgentState) -> dict[str, Any]:
    """LangGraph node for the general chat agent.

    Args:
        state: The current agent state.

    Returns:
        State update dict with the AI response message.
    """
    logger.info("chat_agent_invoked", conversation_id=state.get("conversation_id"))

    llm = llm_service.get_chat_model()

    system_prompt = state.get("system_prompts", {}).get("chat", CHAT_SYSTEM_PROMPT)
    messages = [SystemMessage(content=system_prompt)]
    memory_message = memory_context_message(state)
    if memory_message is not None:
        messages.append(memory_message)
    messages.extend(state["messages"])

    # If no messages from user yet, add the current input
    if not any(isinstance(m, HumanMessage) for m in state["messages"]):
        messages.append(HumanMessage(content=state["user_input"]))

    response = await llm.ainvoke(messages)

    return {
        "messages": [response],
        "current_agent": "chat",
        "tool_calls": state.get("tool_calls", []),
        "metadata": {
            **state.get("metadata", {}),
            "agent_used": "chat",
        },
    }


async def chat_agent_stream(state: AgentState):
    """Streaming version of the chat agent for real-time token delivery.

    Yields individual tokens as they arrive from the LLM.
    """
    llm = llm_service.get_chat_model()

    system_prompt = state.get("system_prompts", {}).get("chat", CHAT_SYSTEM_PROMPT)
    messages = [SystemMessage(content=system_prompt)]
    memory_message = memory_context_message(state)
    if memory_message is not None:
        messages.append(memory_message)
    messages.extend(state["messages"])

    if not any(isinstance(m, HumanMessage) for m in state["messages"]):
        messages.append(HumanMessage(content=state["user_input"]))

    full_response = ""
    async for chunk in llm.astream(messages):
        if chunk.content:
            full_response += str(chunk.content)
            yield {"type": "token", "content": str(chunk.content)}

    yield {
        "type": "done",
        "messages": [AIMessage(content=full_response)],
        "current_agent": "chat",
    }
