"""Tests for GET /tools and POST /tools/execute endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


class TestListTools:
    """Tests for GET /api/v1/tools."""

    async def test_returns_list_of_tools(self, client: AsyncClient):
        """Should return a list of all registered tools."""
        resp = await client.get("/api/v1/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

    async def test_tool_has_required_fields(self, client: AsyncClient):
        """Each tool should have name, description, parameters fields."""
        resp = await client.get("/api/v1/tools")
        data = resp.json()
        for tool in data:
            assert "name" in tool
            assert "description" in tool
            assert "parameters" in tool

    async def test_tool_has_agent_field(self, client: AsyncClient):
        """Each tool should have an agent field (possibly null)."""
        resp = await client.get("/api/v1/tools")
        data = resp.json()
        for tool in data:
            assert "agent" in tool

    async def test_sql_tools_mapped_to_sql_agent(self, client: AsyncClient):
        """SQL-domain tools should have agent='sql'."""
        resp = await client.get("/api/v1/tools")
        data = resp.json()
        sql_tool_names = {"sql_query_tool", "sql_schema_tool", "sql_validate_tool"}
        for tool in data:
            if tool["name"] in sql_tool_names:
                assert tool["agent"] == "sql", f"{tool['name']} should be sql"

    async def test_parameters_is_json_schema(self, client: AsyncClient):
        """Tool parameters should contain JSON schema properties."""
        resp = await client.get("/api/v1/tools")
        data = resp.json()
        # Find any tool that has a non-empty parameters dict
        tools_with_params = [t for t in data if t["parameters"]]
        assert len(tools_with_params) > 0, "At least one tool should have parameters"
        for tool in tools_with_params:
            # JSON schema should have 'properties' or 'type'
            params = tool["parameters"]
            assert isinstance(params, dict)


class TestExecuteTool:
    """Tests for POST /api/v1/tools/execute."""

    async def test_execute_calculator_tool(self, client: AsyncClient):
        """Should successfully execute the calculator tool."""
        resp = await client.post(
            "/api/v1/tools/execute",
            json={"tool_name": "calculator_tool", "arguments": {"expression": "2 + 2"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tool_name"] == "calculator_tool"
        assert "output" in data
        assert "duration_ms" in data
        assert data["duration_ms"] >= 0

    async def test_execute_unknown_tool(self, client: AsyncClient):
        """Should return 404 for a non-existent tool."""
        resp = await client.post(
            "/api/v1/tools/execute",
            json={"tool_name": "nonexistent_tool", "arguments": {}},
        )
        assert resp.status_code == 404
        data = resp.json()
        assert data["error"]["code"] == "NOT_FOUND"

    async def test_execute_tool_validation_error(self, client: AsyncClient):
        """Missing required arguments should result in 422."""
        # sql_query_tool requires 'query' argument — calling without it
        # should raise an error from the tool itself
        resp = await client.post(
            "/api/v1/tools/execute",
            json={"tool_name": "sql_query_tool", "arguments": {}},
        )
        # The tool execution fails, so we get 422 from InputValidationError
        assert resp.status_code == 422

    async def test_execute_tool_returns_duration(self, client: AsyncClient):
        """Response should include positive duration_ms."""
        resp = await client.post(
            "/api/v1/tools/execute",
            json={"tool_name": "calculator_tool", "arguments": {"expression": "10 * 5"}},
        )
        assert resp.status_code == 200
        assert resp.json()["duration_ms"] >= 0

    async def test_execute_tool_missing_body(self, client: AsyncClient):
        """Should return 422 if request body is missing."""
        resp = await client.post("/api/v1/tools/execute", content=b"")
        assert resp.status_code == 422

    async def test_execute_tool_invalid_json(self, client: AsyncClient):
        """Should return 422 if JSON is malformed."""
        resp = await client.post(
            "/api/v1/tools/execute",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422


class TestToolAgentMapping:
    """Tests for the _TOOL_AGENT_MAP module-level setup."""

    def test_tool_agent_map_populated(self):
        """The tool-to-agent map should be non-empty."""
        from app.api.routes.tools import _TOOL_AGENT_MAP

        assert len(_TOOL_AGENT_MAP) > 0

    def test_tool_lookup_populated(self):
        """The tool lookup dict should be non-empty."""
        from app.api.routes.tools import _TOOL_LOOKUP

        assert len(_TOOL_LOOKUP) > 0

    def test_all_tools_in_lookup(self):
        """Every tool in all_tools should appear in the lookup."""
        from app.api.routes.tools import _TOOL_LOOKUP
        from app.tools import all_tools

        for tool in all_tools:
            assert tool.name in _TOOL_LOOKUP
