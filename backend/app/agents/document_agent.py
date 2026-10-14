"""Document Agent — document analysis, parsing, and information extraction.

Handles user requests to analyze uploaded documents, extract text and tables,
perform OCR on images, and answer questions about document content.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agents.memory_context import memory_context_message
from app.agents.state import AgentState
from app.services.llm import llm_service
from app.tools.document_tools import document_tools

logger = structlog.get_logger(__name__)

DOCUMENT_SYSTEM_PROMPT = """You are a document analysis expert. Your job is to help users understand, analyze, and extract information from documents.

You have access to the following tools:
- document_parse_tool: Parse a document and extract its text content
- document_ocr_tool: Extract text from images using OCR
- document_extract_tables_tool: Extract tables from documents
- document_info_tool: Get metadata about a document

WORKFLOW:
1. If the user provides a file path, start by parsing the document.
2. For images, use OCR to extract text.
3. For structured data needs, try extracting tables.
4. Answer the user's questions based on the extracted content.
5. Cite specific sections or pages when referencing document content.

Always provide clear, structured answers based on the actual document content."""


async def document_agent_node(state: AgentState) -> dict[str, Any]:
    """LangGraph node for the document analysis agent.

    This agent:
    1. Parses documents using appropriate tools
    2. Extracts text, tables, and metadata
    3. Answers questions about document content
    """
    logger.info("document_agent_invoked", conversation_id=state.get("conversation_id"))

    llm = llm_service.get_chat_model(temperature=0.1)
    llm_with_tools = llm.bind_tools(document_tools)

    system_prompt = state.get("system_prompts", {}).get("document", DOCUMENT_SYSTEM_PROMPT)
    messages = [SystemMessage(content=system_prompt)]
    memory_message = memory_context_message(state)
    if memory_message is not None:
        messages.append(memory_message)
    messages.extend(state["messages"])

    if not any(isinstance(m, HumanMessage) for m in state["messages"]):
        # Include attachment info if available
        user_msg = state["user_input"]
        if state.get("attachments"):
            attachments_str = "\n".join(f"- {a}" for a in state["attachments"])
            user_msg += f"\n\nAttached files:\n{attachments_str}"
        messages.append(HumanMessage(content=user_msg))

    tool_calls_record: list[dict[str, Any]] = []
    allowed_paths = {Path(path).resolve() for path in state.get("attachments", [])}
    max_iterations = 5

    for iteration in range(max_iterations):
        response = await llm_with_tools.ainvoke(messages)
        messages.append(response)

        if not response.tool_calls:
            break

        for tc in response.tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]

            tool_fn = next((t for t in document_tools if t.name == tool_name), None)
            if tool_fn is None:
                tool_result = f"Unknown tool: {tool_name}"
            else:
                try:
                    path_key = "image_path" if tool_name == "document_ocr_tool" else "file_path"
                    if Path(tool_args[path_key]).resolve() not in allowed_paths:
                        raise ValueError("Document tools can only access attached files.")
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
        "current_agent": "document",
        "tool_calls": state.get("tool_calls", []) + tool_calls_record,
        "metadata": {
            **state.get("metadata", {}),
            "agent_used": "document",
        },
    }
