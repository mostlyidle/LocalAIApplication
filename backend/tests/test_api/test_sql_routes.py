"""Tests for SQL API routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


class TestSQLSchemaEndpoint:
    """Tests for GET /api/v1/sql/schema."""

    async def test_selected_database_is_used(self, client: AsyncClient):
        with patch(
            "app.api.routes.sql.introspect_schema", AsyncMock(return_value={"tables": []})
        ) as inspect:
            response = await client.get("/api/v1/sql/schema?database=secondary")
        assert response.status_code == 200
        inspect.assert_awaited_once_with(database="secondary")

    async def test_returns_schema(self, client: AsyncClient, sql_engine):
        """Verify the schema endpoint returns table information."""
        with patch("app.api.routes.sql.introspect_schema") as mock_introspect:
            mock_introspect.return_value = {
                "database": "default",
                "tables": [
                    {
                        "name": "users",
                        "columns": [
                            {
                                "name": "id",
                                "type": "INTEGER",
                                "nullable": False,
                                "primary_key": True,
                                "foreign_key": None,
                            },
                            {
                                "name": "name",
                                "type": "TEXT",
                                "nullable": False,
                                "primary_key": False,
                                "foreign_key": None,
                            },
                        ],
                    }
                ],
            }

            resp = await client.get("/api/v1/sql/schema")

        assert resp.status_code == 200
        data = resp.json()
        assert data["database"] == "default"
        assert len(data["tables"]) == 1
        assert data["tables"][0]["name"] == "users"

    async def test_schema_error_returns_503(self, client: AsyncClient):
        """When schema introspection fails, it should return a 503."""
        with patch("app.api.routes.sql.introspect_schema") as mock_introspect:
            mock_introspect.side_effect = RuntimeError("DB connection failed")

            resp = await client.get("/api/v1/sql/schema")

        assert resp.status_code == 503


class TestSQLExecuteEndpoint:
    """Tests for POST /api/v1/sql/execute."""

    async def test_selected_database_is_used(self, client: AsyncClient):
        with patch("app.api.routes.sql.execute_query", AsyncMock(return_value={})) as execute:
            response = await client.post(
                "/api/v1/sql/execute", json={"sql": "SELECT 1", "database": "secondary"}
            )
        assert response.status_code == 200
        assert execute.call_args.kwargs["database"] == "secondary"


    async def test_execute_valid_query(self, client: AsyncClient, sql_engine):
        """Execute a valid SELECT query."""
        with (
            patch("app.api.routes.sql.validate_query") as mock_validate,
            patch("app.api.routes.sql.execute_query") as mock_execute,
        ):
            mock_validate.return_value = "SELECT * FROM users LIMIT 100;"
            mock_execute.return_value = {
                "columns": ["id", "name"],
                "rows": [[1, "Alice"], [2, "Bob"]],
                "row_count": 2,
                "execution_time_ms": 1.5,
            }

            resp = await client.post(
                "/api/v1/sql/execute",
                json={"sql": "SELECT * FROM users"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["row_count"] == 2

    async def test_execute_unsafe_query_returns_422(self, client: AsyncClient):
        """Attempting to execute an unsafe query should return 422."""
        from app.api.middleware.error_handler import UnsafeQueryError

        with patch("app.api.routes.sql.validate_query") as mock_validate:
            mock_validate.side_effect = UnsafeQueryError("Only SELECT queries are allowed.")

            resp = await client.post(
                "/api/v1/sql/execute",
                json={"sql": "DROP TABLE users"},
            )

        # InputValidationError wraps UnsafeQueryError => 422
        assert resp.status_code == 422


class TestSQLNaturalLanguageEndpoint:
    """Explicit SQL requests retain connection selection and typed results."""

    async def test_preserves_selected_database_and_result_values(self, client: AsyncClient):
        from langchain_core.messages import AIMessage

        result = {
            "messages": [AIMessage(content="Result")],
            "tool_calls": [
                {
                    "tool_name": "sql_query_tool",
                    "tool_input": {"sql": "SELECT value"},
                    "tool_output": '{"columns":["value"],"rows":[[null],["a|b"],[2]]}',
                }
            ],
        }
        with patch("app.api.routes.sql.sql_agent_node", AsyncMock(return_value=result)) as agent:
            response = await client.post(
                "/api/v1/sql/query", json={"question": "Show values", "database": "secondary"}
            )
        assert response.status_code == 200
        assert agent.call_args.args[0]["database"] == "secondary"
        assert response.json()["generated_sql"] == "SELECT value"
        assert response.json()["rows"] == [[None], ["a|b"], [2]]


class TestSQLConnectionsEndpoint:
    """Tests for SQL connections management endpoints."""

    async def test_list_connections_empty(self, client: AsyncClient):
        """List connections when none are registered."""
        with patch("app.services.database._sql_engines", {}):
            resp = await client.get("/api/v1/sql/connections")

        assert resp.status_code == 200
        assert resp.json() == []
