"""Web Research Agent — fetch, scrape, and summarize web content locally.

Handles web-related queries by fetching URLs, extracting content,
and providing summaries. Runs fully locally without API keys.
"""

from __future__ import annotations

from typing import Any

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agents.memory_context import memory_context_message
from app.agents.state import AgentState
from app.services.llm import llm_service
from app.tools.web_tools import web_tools

logger = structlog.get_logger(__name__)

WEB_SYSTEM_PROMPT = """You are a web research assistant. Your job is to help users fetch, read, and understand web content.

You have access to the following tools:
- web_fetch_tool: Fetch a web page and extract its main text content
- web_search_links_tool: Fetch a page and extract all links from it
- web_multi_fetch_tool: Fetch multiple pages concurrently

WORKFLOW:
1. If the user provides a URL, fetch it directly.
2. If the user asks about a topic without a URL, let them know you need a URL.
3. After fetching content, provide a clear summary.
4. If the page has relevant links, mention them.
5. For comparison tasks, use web_multi_fetch_tool to fetch multiple pages.

IMPORTANT:
- Always summarize the key information from fetched pages.
- Keep summaries concise and focused on what the user asked.
- If a page fails to load, explain the error and suggest alternatives."""


async def web_agent_node(state: AgentState) -> dict[str, Any]:
    """LangGraph node for the web research agent.

    This agent:
    1. Fetches web pages using HTTP
    2. Extracts and cleans text content
    3. Summarizes and presents information
    """
    logger.info("web_agent_invoked", conversation_id=state.get("conversation_id"))

    llm = llm_service.get_chat_model(temperature=0.2)
    available_tools = web_tools + state.get("external_tools", [])
    llm_with_tools = llm.bind_tools(available_tools)

    system_prompt = state.get("system_prompts", {}).get("web", WEB_SYSTEM_PROMPT)
    messages = [SystemMessage(content=system_prompt)]
    memory_message = memory_context_message(state)
    if memory_message is not None:
        messages.append(memory_message)
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

            tool_fn = next((t for t in available_tools if t.name == tool_name), None)
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
        "current_agent": "web",
        "tool_calls": state.get("tool_calls", []) + tool_calls_record,
        "metadata": {
            **state.get("metadata", {}),
            "agent_used": "web",
        },
    }
