"""Tests for the 5 specialist agents: chat, sql, document, rag, web.

All tests mock the LLM to return deterministic responses.
We verify:
  - Correct state dict returned (messages, current_agent, metadata)
  - Tool call loop for tool-using agents
  - Graceful error handling for unknown tools
  - System prompts are included
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


# =============================================================================
# Helpers
# =============================================================================


def _make_state(**overrides: Any) -> dict:
    """Build a minimal AgentState-compatible dict."""
    base = {
        "messages": [HumanMessage(content="Hello")],
        "current_agent": "orchestrator",
        "next_agent": None,
        "user_input": "Hello",
        "attachments": [],
        "conversation_id": "test-conv-1",
        "tool_calls": [],
        "metadata": {},
        "error": None,
    }
    base.update(overrides)
    return base


def _mock_llm_response(
    content: str = "I can help with that.", tool_calls: list | None = None
) -> MagicMock:
    """Create a mock AIMessage response."""
    msg = MagicMock(spec=AIMessage)
    msg.content = content
    msg.tool_calls = tool_calls or []
    return msg


def _mock_llm_service(response: MagicMock | None = None) -> MagicMock:
    """Create a mock LLMService with a mock ChatOllama."""
    if response is None:
        response = _mock_llm_response()

    mock_chat_model = MagicMock()
    mock_chat_model.ainvoke = AsyncMock(return_value=response)
    mock_chat_model.bind_tools = MagicMock(return_value=mock_chat_model)
    mock_chat_model.astream = AsyncMock()

    mock_service = MagicMock()
    mock_service.get_chat_model = MagicMock(return_value=mock_chat_model)
    return mock_service


# =============================================================================
# Chat Agent
# =============================================================================


class TestChatAgent:
    async def test_basic_response(self) -> None:
        response = _mock_llm_response("Hello! How can I help?")
        mock_service = _mock_llm_service(response)

        with patch("app.agents.chat_agent.llm_service", mock_service):
            from app.agents.chat_agent import chat_agent_node

            state = _make_state()
            result = await chat_agent_node(state)

        assert result["current_agent"] == "chat"
        assert len(result["messages"]) == 1
        assert result["messages"][0].content == "Hello! How can I help?"
        assert result["metadata"]["agent_used"] == "chat"

    async def test_adds_user_input_when_no_human_messages(self) -> None:
        response = _mock_llm_response("Response")
        mock_service = _mock_llm_service(response)

        with patch("app.agents.chat_agent.llm_service", mock_service):
            from app.agents.chat_agent import chat_agent_node

            state = _make_state(messages=[], user_input="New question")
            result = await chat_agent_node(state)

        # Verify ainvoke was called with messages including the user input
        call_args = mock_service.get_chat_model().ainvoke.call_args[0][0]
        human_msgs = [m for m in call_args if isinstance(m, HumanMessage)]
        assert any("New question" in m.content for m in human_msgs)

    async def test_preserves_existing_metadata(self) -> None:
        response = _mock_llm_response("ok")
        mock_service = _mock_llm_service(response)

        with patch("app.agents.chat_agent.llm_service", mock_service):
            from app.agents.chat_agent import chat_agent_node

            state = _make_state(metadata={"existing_key": "value"})
            result = await chat_agent_node(state)

        assert result["metadata"]["existing_key"] == "value"
        assert result["metadata"]["agent_used"] == "chat"


# =============================================================================
# SQL Agent
# =============================================================================


class TestSQLAgent:
    async def test_basic_sql_response(self) -> None:
        response = _mock_llm_response("The top customers are...")
        mock_service = _mock_llm_service(response)

        with (
            patch("app.agents.sql_agent.llm_service", mock_service),
            patch(
                "app.agents.sql_agent.introspect_schema",
                new_callable=AsyncMock,
                return_value={"tables": [{"name": "users", "columns": []}]},
            ),
            patch(
                "app.agents.sql_agent.format_schema_for_prompt",
                return_value="TABLE users (id, name)",
            ),
        ):
            from app.agents.sql_agent import sql_agent_node

            state = _make_state(user_input="Show top customers")
            result = await sql_agent_node(state)

        assert result["current_agent"] == "sql"
        assert result["metadata"]["agent_used"] == "sql"

    async def test_tool_call_loop(self) -> None:
        """SQL agent should execute tool calls and loop."""
        # First call returns a tool call, second returns plain text
        tool_call_response = _mock_llm_response(
            "", tool_calls=[{"name": "sql_query_tool", "args": {"query": "SELECT 1"}, "id": "tc1"}]
        )
        final_response = _mock_llm_response("Result is 1.")

        mock_chat_model = MagicMock()
        mock_chat_model.ainvoke = AsyncMock(side_effect=[tool_call_response, final_response])
        mock_chat_model.bind_tools = MagicMock(return_value=mock_chat_model)

        mock_service = MagicMock()
        mock_service.get_chat_model = MagicMock(return_value=mock_chat_model)

        mock_tool = AsyncMock()
        mock_tool.name = "sql_query_tool"
        mock_tool.ainvoke = AsyncMock(return_value="1")

        with (
            patch("app.agents.sql_agent.llm_service", mock_service),
            patch(
                "app.agents.sql_agent.introspect_schema",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("app.agents.sql_agent.format_schema_for_prompt", return_value=""),
            patch("app.agents.sql_agent.sql_tools", [mock_tool]),
        ):
            from app.agents.sql_agent import sql_agent_node

            state = _make_state(user_input="SELECT 1")
            result = await sql_agent_node(state)

        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["tool_name"] == "sql_query_tool"

    async def test_preserves_named_database_from_chat_tool_call(self) -> None:
        """Chat SQL tool calls retain their named database without selected state."""
        tool_call_response = _mock_llm_response(
            "",
            tool_calls=[
                {
                    "name": "sql_query_tool",
                    "args": {"query": "SELECT 1", "database": "named"},
                    "id": "tc-chat-db",
                }
            ],
        )
        final_response = _mock_llm_response("Result is 1.")

        mock_chat_model = MagicMock()
        mock_chat_model.ainvoke = AsyncMock(side_effect=[tool_call_response, final_response])
        mock_chat_model.bind_tools = MagicMock(return_value=mock_chat_model)

        mock_service = MagicMock()
        mock_service.get_chat_model = MagicMock(return_value=mock_chat_model)
        mock_tool = AsyncMock()
        mock_tool.name = "sql_query_tool"
        mock_tool.ainvoke = AsyncMock(return_value="1")

        with (
            patch("app.agents.sql_agent.llm_service", mock_service),
            patch(
                "app.agents.sql_agent.introspect_schema",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("app.agents.sql_agent.format_schema_for_prompt", return_value=""),
            patch("app.agents.sql_agent.sql_tools", [mock_tool]),
        ):
            from app.agents.sql_agent import sql_agent_node

            result = await sql_agent_node(_make_state(user_input="SELECT 1"))

        assert result["tool_calls"][0]["tool_input"]["database"] == "named"
        mock_tool.ainvoke.assert_awaited_once_with(
            {"query": "SELECT 1", "database": "named"}
        )

    async def test_authoritative_state_database_overrides_tool_database(self) -> None:
        """An explicitly selected state database takes precedence over tool arguments."""
        tool_call_response = _mock_llm_response(
            "",
            tool_calls=[
                {
                    "name": "sql_query_tool",
                    "args": {"query": "SELECT 1", "database": "tool-named"},
                    "id": "tc-state-db",
                }
            ],
        )
        final_response = _mock_llm_response("Result is 1.")

        mock_chat_model = MagicMock()
        mock_chat_model.ainvoke = AsyncMock(side_effect=[tool_call_response, final_response])
        mock_chat_model.bind_tools = MagicMock(return_value=mock_chat_model)

        mock_service = MagicMock()
        mock_service.get_chat_model = MagicMock(return_value=mock_chat_model)
        mock_tool = AsyncMock()
        mock_tool.name = "sql_query_tool"
        mock_tool.ainvoke = AsyncMock(return_value="1")

        with (
            patch("app.agents.sql_agent.llm_service", mock_service),
            patch(
                "app.agents.sql_agent.introspect_schema",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("app.agents.sql_agent.format_schema_for_prompt", return_value=""),
            patch("app.agents.sql_agent.sql_tools", [mock_tool]),
        ):
            from app.agents.sql_agent import sql_agent_node

            result = await sql_agent_node(
                _make_state(user_input="SELECT 1", database="authoritative")
            )

        assert result["tool_calls"][0]["tool_input"]["database"] == "authoritative"
        mock_tool.ainvoke.assert_awaited_once_with(
            {"query": "SELECT 1", "database": "authoritative"}
        )

    async def test_schema_introspection_failure(self) -> None:
        """Agent handles schema introspection failure gracefully."""
        response = _mock_llm_response("I cannot inspect the schema right now.")
        mock_service = _mock_llm_service(response)

        with (
            patch("app.agents.sql_agent.llm_service", mock_service),
            patch(
                "app.agents.sql_agent.introspect_schema",
                new_callable=AsyncMock,
                side_effect=Exception("DB error"),
            ),
            patch("app.agents.sql_agent.format_schema_for_prompt", return_value=""),
        ):
            from app.agents.sql_agent import sql_agent_node

            state = _make_state()
            result = await sql_agent_node(state)

        assert result["current_agent"] == "sql"

    async def test_unknown_tool_handled(self) -> None:
        """Unknown tool calls return error messages instead of crashing."""
        tool_call_response = _mock_llm_response(
            "", tool_calls=[{"name": "nonexistent_tool", "args": {}, "id": "tc2"}]
        )
        final_response = _mock_llm_response("Sorry, that tool doesn't exist.")

        mock_chat_model = MagicMock()
        mock_chat_model.ainvoke = AsyncMock(side_effect=[tool_call_response, final_response])
        mock_chat_model.bind_tools = MagicMock(return_value=mock_chat_model)

        mock_service = MagicMock()
        mock_service.get_chat_model = MagicMock(return_value=mock_chat_model)

        with (
            patch("app.agents.sql_agent.llm_service", mock_service),
            patch(
                "app.agents.sql_agent.introspect_schema",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("app.agents.sql_agent.format_schema_for_prompt", return_value=""),
            patch("app.agents.sql_agent.sql_tools", []),
        ):
            from app.agents.sql_agent import sql_agent_node

            state = _make_state()
            result = await sql_agent_node(state)

        assert result["tool_calls"][0]["tool_output"].startswith("Unknown tool")


# =============================================================================
# Document Agent
# =============================================================================


class TestDocumentAgent:
    async def test_basic_response(self) -> None:
        response = _mock_llm_response("The document contains a report.")
        mock_service = _mock_llm_service(response)

        with patch("app.agents.document_agent.llm_service", mock_service):
            from app.agents.document_agent import document_agent_node

            state = _make_state(user_input="What is in this document?")
            result = await document_agent_node(state)

        assert result["current_agent"] == "document"
        assert result["metadata"]["agent_used"] == "document"

    async def test_includes_attachments(self) -> None:
        response = _mock_llm_response("Parsing /tmp/report.pdf...")
        mock_service = _mock_llm_service(response)

        with patch("app.agents.document_agent.llm_service", mock_service):
            from app.agents.document_agent import document_agent_node

            state = _make_state(
                messages=[],
                user_input="Analyze this file",
                attachments=["/tmp/report.pdf"],
            )
            result = await document_agent_node(state)

        # Verify the attachment was included in the message
        call_args = mock_service.get_chat_model().ainvoke.call_args
        # bind_tools returns the same mock, so ainvoke is on the same object
        messages = call_args[0][0]
        human_msgs = [m for m in messages if isinstance(m, HumanMessage)]
        assert any("/tmp/report.pdf" in m.content for m in human_msgs)

    async def test_tool_call_and_error(self) -> None:
        tool_call_response = _mock_llm_response(
            "",
            tool_calls=[
                {"name": "document_parse_tool", "args": {"file_path": "/tmp/doc.txt"}, "id": "tc1"}
            ],
        )
        final_response = _mock_llm_response("Error parsing the document.")

        mock_chat_model = MagicMock()
        mock_chat_model.ainvoke = AsyncMock(side_effect=[tool_call_response, final_response])
        mock_chat_model.bind_tools = MagicMock(return_value=mock_chat_model)

        mock_service = MagicMock()
        mock_service.get_chat_model = MagicMock(return_value=mock_chat_model)

        mock_tool = AsyncMock()
        mock_tool.name = "document_parse_tool"
        mock_tool.ainvoke = AsyncMock(side_effect=Exception("Parse failed"))

        with (
            patch("app.agents.document_agent.llm_service", mock_service),
            patch("app.agents.document_agent.document_tools", [mock_tool]),
        ):
            from app.agents.document_agent import document_agent_node

            state = _make_state()
            result = await document_agent_node(state)

        assert result["tool_calls"][0]["tool_output"].startswith("Tool error")


# =============================================================================
# RAG Agent
# =============================================================================


class TestRAGAgent:
    async def test_retrieves_full_cited_passages_before_generation(self) -> None:
        from types import SimpleNamespace
        from app.agents.rag_agent import rag_agent_node

        calls = []
        evidence = "Background " * 80 + "Revenue was $10M."
        async def retrieve(**kwargs):
            calls.append("retrieve")
            return SimpleNamespace(passages=[{"content": evidence, "metadata": {"asset_id": "report", "chunk_index": 3, "source": "report.pdf", "page": 4, "section": "Revenue"}}], retrieval={"strategy": "hybrid_rrf"})
        async def generate(messages):
            calls.append("generate")
            assert evidence in messages[1].content
            assert "[report:3]" in messages[1].content
            return AIMessage(content="Revenue was $10M [report:3].")
        model = MagicMock()
        model.ainvoke = AsyncMock(side_effect=generate)
        with (
            patch("app.agents.rag_agent.llm_service.get_chat_model", return_value=model),
            patch("app.services.hybrid_vector_store.hybrid_vector_store_service.search_with_provenance", AsyncMock(side_effect=retrieve)),
        ):
            result = await rag_agent_node(_make_state(user_input="What was revenue?"))
        assert calls == ["retrieve", "generate"]
        assert result["metadata"]["execution"]["artifacts"]["citations"][0]["section"] == "Revenue"
        assert result["metadata"]["execution"]["artifacts"]["citations"][0]["chunk_index"] == 3

    async def test_no_evidence_never_invokes_answer_model(self) -> None:
        from types import SimpleNamespace
        from app.agents.rag_agent import rag_agent_node
        with (
            patch("app.agents.rag_agent.llm_service.get_chat_model") as generate,
            patch("app.services.hybrid_vector_store.hybrid_vector_store_service.search_with_provenance", AsyncMock(return_value=SimpleNamespace(passages=[], retrieval={}))),
        ):
            result = await rag_agent_node(_make_state(user_input="What was revenue?"))
        generate.assert_not_called()
        assert "could not find" in result["messages"][0].content
        assert result["metadata"]["execution"]["artifacts"]["citations"] == []


# =============================================================================
# Web Agent
# =============================================================================


class TestWebAgent:
    async def test_basic_response(self) -> None:
        response = _mock_llm_response("I need a URL to fetch content.")
        mock_service = _mock_llm_service(response)

        with patch("app.agents.web_agent.llm_service", mock_service):
            from app.agents.web_agent import web_agent_node

            state = _make_state(user_input="Research Python trends")
            result = await web_agent_node(state)

        assert result["current_agent"] == "web"
        assert result["metadata"]["agent_used"] == "web"

    async def test_fetch_tool_call(self) -> None:
        tool_call_response = _mock_llm_response(
            "",
            tool_calls=[
                {"name": "web_fetch_tool", "args": {"url": "https://example.com"}, "id": "tc1"}
            ],
        )
        final_response = _mock_llm_response("The page discusses Python trends.")

        mock_chat_model = MagicMock()
        mock_chat_model.ainvoke = AsyncMock(side_effect=[tool_call_response, final_response])
        mock_chat_model.bind_tools = MagicMock(return_value=mock_chat_model)

        mock_service = MagicMock()
        mock_service.get_chat_model = MagicMock(return_value=mock_chat_model)

        mock_tool = AsyncMock()
        mock_tool.name = "web_fetch_tool"
        mock_tool.ainvoke = AsyncMock(return_value="Page content: Python trends 2025")

        with (
            patch("app.agents.web_agent.llm_service", mock_service),
            patch("app.agents.web_agent.web_tools", [mock_tool]),
        ):
            from app.agents.web_agent import web_agent_node

            state = _make_state(user_input="Fetch https://example.com")
            result = await web_agent_node(state)

        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["tool_name"] == "web_fetch_tool"

    async def test_unknown_tool_handled(self) -> None:
        tool_call_response = _mock_llm_response(
            "", tool_calls=[{"name": "bad_tool", "args": {}, "id": "tc1"}]
        )
        final_response = _mock_llm_response("That tool is not available.")

        mock_chat_model = MagicMock()
        mock_chat_model.ainvoke = AsyncMock(side_effect=[tool_call_response, final_response])
        mock_chat_model.bind_tools = MagicMock(return_value=mock_chat_model)

        mock_service = MagicMock()
        mock_service.get_chat_model = MagicMock(return_value=mock_chat_model)

        with (
            patch("app.agents.web_agent.llm_service", mock_service),
            patch("app.agents.web_agent.web_tools", []),
        ):
            from app.agents.web_agent import web_agent_node

            state = _make_state()
            result = await web_agent_node(state)

        assert result["tool_calls"][0]["tool_output"].startswith("Unknown tool")


# =============================================================================
# Agent state helpers
# =============================================================================


class TestAgentState:
    def test_create_initial_state(self) -> None:
        from app.agents.state import create_initial_state

        state = create_initial_state(
            user_input="Hello",
            conversation_id="conv-123",
            attachments=["/tmp/file.pdf"],
        )
        assert state["user_input"] == "Hello"
        assert state["conversation_id"] == "conv-123"
        assert state["attachments"] == ["/tmp/file.pdf"]
        assert state["current_agent"] == "orchestrator"
        assert state["messages"] == []
        assert state["tool_calls"] == []
        assert state["error"] is None

    def test_create_initial_state_no_attachments(self) -> None:
        from app.agents.state import create_initial_state

        state = create_initial_state(
            user_input="test",
            conversation_id="conv-456",
        )
        assert state["attachments"] == []
