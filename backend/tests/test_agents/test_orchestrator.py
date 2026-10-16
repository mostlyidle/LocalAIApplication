"""Tests for the orchestrator — intent classification and routing.

These tests mock the LLM so they run fully offline and deterministically.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.orchestrator import (
    _heuristic_classify,
    _parse_classification,
    classify_intent,
    route_to_agent,
)
from app.agents.state import AgentState, create_initial_state
from app.models.enums import AgentType


# =============================================================================
# _heuristic_classify — pure function
# =============================================================================


class TestHeuristicClassify:
    """Tests for the keyword-based fast classifier."""

    def test_url_routes_to_web(self):
        assert _heuristic_classify("fetch https://example.com", []) == AgentType.WEB

    def test_http_url_routes_to_web(self):
        assert _heuristic_classify("read http://example.com/page", []) == AgentType.WEB

    def test_attachments_with_action_routes_to_document(self):
        result = _heuristic_classify("parse this file", ["report.pdf"])
        assert result == AgentType.DOCUMENT

    def test_attachments_without_action_returns_none(self):
        result = _heuristic_classify("hello", ["report.pdf"])
        assert result is None

    def test_sql_keywords_route_to_sql(self):
        assert _heuristic_classify("query the database for users", []) == AgentType.SQL

    def test_select_keyword(self):
        assert _heuristic_classify("select all from users", []) == AgentType.SQL

    def test_schema_keyword(self):
        assert _heuristic_classify("show me the schema", []) == AgentType.SQL

    def test_rag_keywords(self):
        result = _heuristic_classify("search documents for revenue data", [])
        assert result == AgentType.RAG

    def test_knowledge_base_keyword(self):
        result = _heuristic_classify("look in the knowledge base", [])
        assert result == AgentType.RAG

    def test_generic_message_returns_none(self):
        assert _heuristic_classify("hello how are you", []) is None

    def test_ambiguous_returns_none(self):
        assert _heuristic_classify("what's the weather?", []) is None


# =============================================================================
# _parse_classification — pure function
# =============================================================================


class TestParseClassification:
    """Tests for parsing the LLM classification response."""

    def test_clean_json(self):
        assert _parse_classification('{"agent": "sql"}') == "sql"

    def test_json_with_extra_whitespace(self):
        assert _parse_classification('  {"agent": "document"}  ') == "document"

    def test_rejects_json_in_markdown_code_block(self):
        content = '```json\n{"agent": "web"}\n```'
        assert _parse_classification(content) == "chat"

    def test_rejects_plain_text_agent_name(self):
        result = _parse_classification("I think this is a sql question.")
        assert result == "chat"

    def test_fallback_to_chat(self):
        result = _parse_classification("I have no idea what this is.")
        assert result == AgentType.CHAT

    def test_invalid_agent_name(self):
        result = _parse_classification('{"agent": "nonexistent"}')
        assert result == AgentType.CHAT

    def test_empty_string(self):
        result = _parse_classification("")
        assert result == AgentType.CHAT


# =============================================================================
# route_to_agent — pure function
# =============================================================================


class TestRouteToAgent:
    """Tests for the conditional edge function."""

    def test_routes_to_chat(self):
        state = create_initial_state("hello", "conv-1")
        state["next_agent"] = AgentType.CHAT
        assert route_to_agent(state) == AgentType.CHAT

    def test_routes_to_sql(self):
        state = create_initial_state("query", "conv-1")
        state["next_agent"] = AgentType.SQL
        assert route_to_agent(state) == AgentType.SQL

    def test_invalid_agent_falls_back_to_chat(self):
        state = create_initial_state("test", "conv-1")
        state["next_agent"] = "nonexistent"
        assert route_to_agent(state) == AgentType.CHAT

    def test_none_agent_falls_back_to_chat(self):
        state = create_initial_state("test", "conv-1")
        state["next_agent"] = None
        assert route_to_agent(state) == AgentType.CHAT


# =============================================================================
# classify_intent — async, requires mocked LLM
# =============================================================================


class TestClassifyIntent:
    """Tests for the full intent classification node (mocked LLM)."""

    async def test_heuristic_bypass(self):
        """If heuristic matches, the LLM should NOT be called."""
        state = create_initial_state("https://example.com/article", "conv-1")

        result = await classify_intent(state)

        assert result["next_agent"] == AgentType.WEB
        assert result["current_agent"] == "orchestrator"

    async def test_llm_classification(self, mock_llm):
        """When heuristic returns None, it falls through to the LLM."""
        mock_llm.ainvoke.return_value.content = '{"agent": "sql"}'

        state = create_initial_state("how many orders last month", "conv-1")

        with patch("app.agents.orchestrator.llm_service") as mock_service:
            mock_service.get_chat_model.return_value = mock_llm
            result = await classify_intent(state)

        assert result["next_agent"] == "sql"
        schema = mock_service.get_chat_model.call_args.kwargs["format"]
        assert schema["properties"]["agent"]
        assert schema["required"] == ["agent"]

    async def test_recent_events_can_route_to_web_without_a_url(self, mock_llm):
        mock_llm.ainvoke.return_value.content = '{"agent": "web"}'
        state = create_initial_state("Who played last night in the MLB playoffs?", "conv-1")

        with patch("app.agents.orchestrator.llm_service") as mock_service:
            mock_service.get_chat_model.return_value = mock_llm
            result = await classify_intent(state)

        assert result["next_agent"] == AgentType.WEB
        prompt = mock_llm.ainvoke.call_args.args[0][0].content
        assert "recent-events question" in prompt
        assert "even without a URL" in prompt

    async def test_llm_failure_falls_back_to_chat(self, mock_llm):
        """If the LLM call throws, we gracefully fall back to chat."""
        mock_llm.ainvoke.side_effect = RuntimeError("Ollama offline")

        state = create_initial_state("some question", "conv-1")

        with patch("app.agents.orchestrator.llm_service") as mock_service:
            mock_service.get_chat_model.return_value = mock_llm
            result = await classify_intent(state)

        assert result["next_agent"] == AgentType.CHAT
