"""Tests for app.mcp.servers.sql_server — MCP server for SQL tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.servers.sql_server import (
    get_schema,
    list_connections,
    query_database,
    validate_sql,
)


# =============================================================================
# query_database
# =============================================================================


class TestQueryDatabase:
    """Test the query_database MCP tool."""

    async def test_successful_query(self):
        with (
            patch(
                "app.tools.sql_tools.validate_query", return_value="SELECT * FROM users LIMIT 100;"
            ),
            patch(
                "app.tools.sql_tools.execute_query",
                new_callable=AsyncMock,
                return_value={
                    "columns": ["id", "name"],
                    "rows": [[1, "Alice"], [2, "Bob"]],
                    "row_count": 2,
                },
            ),
        ):
            result = await query_database("SELECT * FROM users")

        assert "id" in result
        assert "Alice" in result
        assert "Bob" in result

    async def test_validation_error(self):
        with patch(
            "app.tools.sql_tools.validate_query",
            side_effect=ValueError("DROP not allowed"),
        ):
            result = await query_database("DROP TABLE users")

        assert "Validation error" in result
        assert "DROP" in result

    async def test_execution_error(self):
        with (
            patch("app.tools.sql_tools.validate_query", return_value="SELECT 1"),
            patch(
                "app.tools.sql_tools.execute_query",
                new_callable=AsyncMock,
                side_effect=RuntimeError("DB connection failed"),
            ),
        ):
            result = await query_database("SELECT 1")

        assert "Execution error" in result

    async def test_no_results(self):
        with (
            patch("app.tools.sql_tools.validate_query", return_value="SELECT * FROM empty"),
            patch(
                "app.tools.sql_tools.execute_query",
                new_callable=AsyncMock,
                return_value={"columns": ["id"], "rows": [], "row_count": 0},
            ),
        ):
            result = await query_database("SELECT * FROM empty")

        assert "no results" in result.lower()

    async def test_truncation_at_50_rows(self):
        """Rows beyond 50 should be truncated with a total count."""
        rows = [[i, f"user_{i}"] for i in range(100)]
        with (
            patch("app.tools.sql_tools.validate_query", return_value="SELECT * FROM big"),
            patch(
                "app.tools.sql_tools.execute_query",
                new_callable=AsyncMock,
                return_value={"columns": ["id", "name"], "rows": rows, "row_count": 100},
            ),
        ):
            result = await query_database("SELECT * FROM big")

        assert "100 total rows" in result


# =============================================================================
# validate_sql
# =============================================================================


class TestValidateSql:
    """Test the validate_sql MCP tool."""

    async def test_valid_query(self):
        with patch(
            "app.tools.sql_tools.validate_query",
            return_value="SELECT * FROM users LIMIT 100;",
        ):
            result = await validate_sql("SELECT * FROM users")

        assert "Valid query" in result

    async def test_unsafe_query(self):
        with patch(
            "app.tools.sql_tools.validate_query",
            side_effect=ValueError("Only SELECT queries allowed"),
        ):
            result = await validate_sql("DELETE FROM users")

        assert "UNSAFE" in result


# =============================================================================
# get_schema (MCP resource)
# =============================================================================


class TestGetSchema:
    """Test the schema resource."""

    async def test_returns_formatted_schema(self):
        mock_schema = [{"table": "users", "columns": []}]
        with (
            patch(
                "app.tools.sql_tools.introspect_schema",
                new_callable=AsyncMock,
                return_value=mock_schema,
            ),
            patch(
                "app.tools.sql_tools.format_schema_for_prompt",
                return_value="TABLE: users\n  id INTEGER",
            ),
        ):
            result = await get_schema("default")

        assert "users" in result

    async def test_error_handling(self):
        with patch(
            "app.tools.sql_tools.introspect_schema",
            new_callable=AsyncMock,
            side_effect=RuntimeError("No such database"),
        ):
            result = await get_schema("nonexistent")

        assert "error" in result.lower()


# =============================================================================
# list_connections (MCP resource)
# =============================================================================


class TestListConnections:
    """Test the connections resource."""

    async def test_lists_connections(self):
        mock_engine = MagicMock()
        mock_engine.url = "sqlite:///./data/demo.db"

        with patch(
            "app.services.database._sql_engines",
            {"default": mock_engine},
        ):
            result = await list_connections()

        assert "default" in result
