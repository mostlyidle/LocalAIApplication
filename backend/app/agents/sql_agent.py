"""SQL Agent — natural language to SQL query formulation and execution.

Converts user questions into SQL queries, validates them for safety,
executes against the target database, and provides natural language
explanations of the results.
"""

from __future__ import annotations

from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.memory_context import memory_context_message
from app.agents.state import AgentState
from app.services.llm import llm_service
from app.tools.sql_tools import (
    format_schema_for_prompt,
    introspect_schema,
    sql_tools,
)

logger = structlog.get_logger(__name__)

SQL_SYSTEM_PROMPT_TEMPLATE = """You are an expert SQL analyst. Your job is to help users query databases using natural language.

You have access to the following tools:
- sql_schema_tool: Get the database schema (tables, columns, types, keys)
- sql_query_tool: Execute a validated SQL query
- sql_validate_tool: Validate a SQL query before executing

IMPORTANT RULES:
1. ALWAYS inspect the schema first before writing queries (use sql_schema_tool).
2. Write only SELECT queries unless explicitly told to modify data.
3. Always include a LIMIT clause to prevent unbounded results.
4. Use proper JOIN syntax and avoid cartesian products.
5. After getting results, provide a clear natural language explanation.
6. If the query fails, analyze the error and try a corrected query.

{schema_context}

When you have the answer, respond with:
1. The SQL query you used
2. A clear explanation of the results
3. Any observations or insights from the data"""


async def sql_agent_node(state: AgentState) -> dict[str, Any]:
    """LangGraph node for the SQL agent.

    This agent:
    1. Introspects the database schema
    2. Generates SQL from natural language
    3. Validates and executes the query
    4. Returns results with explanation
    """
    logger.info("sql_agent_invoked", conversation_id=state.get("conversation_id"))

    # Introspect schema to include in system prompt
    try:
        schema = await introspect_schema(database=state.get("database", "default"))
        schema_context = f"DATABASE SCHEMA:\n{format_schema_for_prompt(schema)}"
    except Exception as exc:
        logger.warning("schema_introspection_failed", error=str(exc))
        schema_context = "Database schema not available. Use sql_schema_tool to inspect."

    system_prompt = state.get("system_prompts", {}).get("sql", SQL_SYSTEM_PROMPT_TEMPLATE)
    system_prompt = f"{system_prompt}\n\n{schema_context}"

    llm = llm_service.get_chat_model(temperature=0.0)
    available_tools = sql_tools + state.get("external_tools", [])
    llm_with_tools = llm.bind_tools(available_tools)

    messages = [SystemMessage(content=system_prompt)]
    memory_message = memory_context_message(state)
    if memory_message is not None:
        messages.append(memory_message)
    messages.extend(state["messages"])

    if not any(isinstance(m, HumanMessage) for m in state["messages"]):
        messages.append(HumanMessage(content=state["user_input"]))

    # Run the agent loop (tool calling)
    tool_calls_record: list[dict[str, Any]] = []
    max_iterations = 5
    selected_database = state.get("database", "default")

    for iteration in range(max_iterations):
        response = await llm_with_tools.ainvoke(messages)
        messages.append(response)

        # If no tool calls, the agent is done
        if not response.tool_calls:
            break

        # Execute tool calls
        from langchain_core.messages import ToolMessage

        for tc in response.tool_calls:
            tool_name = tc["name"]
            tool_args = dict(tc["args"])
            if tool_name in {"sql_query_tool", "sql_schema_tool", "sql_validate_tool"}:
                tool_args["database"] = selected_database

            # Find the matching tool
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
                    "tool_output": str(tool_result),
                }
            )

            messages.append(ToolMessage(content=str(tool_result), tool_call_id=tc["id"]))

    return {
        "messages": [response],
        "current_agent": "sql",
        "tool_calls": state.get("tool_calls", []) + tool_calls_record,
        "metadata": {
            **state.get("metadata", {}),
            "agent_used": "sql",
        },
    }
