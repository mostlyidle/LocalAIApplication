"""RAG Agent — retrieval-augmented generation for document-grounded answers.

Searches the vector store for relevant document chunks and generates
answers grounded in the retrieved context, with source citations.
"""

from __future__ import annotations

from typing import Any

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agents.state import AgentState
from app.services.llm import llm_service
from app.tools.rag_tools import rag_tools

logger = structlog.get_logger(__name__)

RAG_SYSTEM_PROMPT = """You are a knowledge retrieval expert. Your job is to answer questions using information from the document knowledge base.

You have access to the following tools:
- rag_search_tool: Search the knowledge base for relevant information
- rag_ingest_tool: Ingest a document into the knowledge base
- rag_list_collections_tool: List available document collections

IMPORTANT RULES:
1. ALWAYS search the knowledge base before answering questions about documents.
2. Base your answers on the retrieved context — do not make up information.
3. ALWAYS cite your sources (document name, page number if available).
4. If the knowledge base doesn't contain relevant information, say so clearly.
5. If results have low relevance scores, acknowledge the uncertainty.

Answer format:
- Provide a clear, direct answer
- Include citations in [Source: filename, Page X] format
- Note if the information might be incomplete or uncertain"""


async def rag_agent_node(state: AgentState) -> dict[str, Any]:
    """LangGraph node for the RAG agent.

    This agent:
    1. Searches the vector store for relevant context
    2. Generates an answer grounded in retrieved documents
    3. Provides source citations
    """
    logger.info("rag_agent_invoked", conversation_id=state.get("conversation_id"))

    llm = llm_service.get_chat_model(temperature=0.1)
    llm_with_tools = llm.bind_tools(rag_tools)

    messages = [SystemMessage(content=RAG_SYSTEM_PROMPT)]
    messages.extend(state["messages"])

    if not any(isinstance(m, HumanMessage) for m in state["messages"]):
        messages.append(HumanMessage(content=state["user_input"]))

    tool_calls_record: list[dict[str, Any]] = []
    max_iterations = 5

    for iteration in range(max_iterations):
        response = await llm_with_tools.ainvoke(messages)
        messages.append(response)

        if not response.tool_calls:
            break

        for tc in response.tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]

            tool_fn = next((t for t in rag_tools if t.name == tool_name), None)
            if tool_fn is None:
                tool_result = f"Unknown tool: {tool_name}"
            else:
                try:
                    tool_result = await tool_fn.ainvoke(tool_args)
                except Exception as exc:
                    tool_result = f"Tool error: {exc}"

            tool_calls_record.append(
                {
                    "tool_name": tool_name,
                    "tool_input": tool_args,
                    "tool_output": str(tool_result)[:2000],
                }
            )

            messages.append(ToolMessage(content=str(tool_result), tool_call_id=tc["id"]))

    return {
        "messages": [response],
        "current_agent": "rag",
        "tool_calls": state.get("tool_calls", []) + tool_calls_record,
        "metadata": {
            **state.get("metadata", {}),
            "agent_used": "rag",
        },
    }
