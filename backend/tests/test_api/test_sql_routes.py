"""Tests for SQL API routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from app.models.db_models import LEGACY_ACCOUNT_ID, SqlConnection


class TestSQLSchemaEndpoint:
    """Tests for GET /api/v1/sql/schema."""

    async def test_selected_database_is_used(self, client: AsyncClient, db_session, sql_engine):
        db_session.add(SqlConnection(name="secondary", owner_id=LEGACY_ACCOUNT_ID))
        await db_session.commit()
        with patch(
            "app.api.routes.sql.introspect_schema", AsyncMock(return_value={"tables": []})
        ) as inspect, patch("app.services.database._sql_engines", {"secondary": sql_engine}):
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

    async def test_selected_database_is_used(self, client: AsyncClient, sql_engine, db_session):
        db_session.add(SqlConnection(name="secondary", owner_id=LEGACY_ACCOUNT_ID))
        await db_session.commit()
        with (
            patch("app.tools.sql_tools.get_sql_engine", return_value=sql_engine) as engine,
            patch("app.api.routes.sql.execute_query", AsyncMock(return_value={})) as execute,
            patch("app.services.database._sql_engines", {"secondary": sql_engine}),
        ):
            response = await client.post(
                "/api/v1/sql/execute", json={"sql": "SELECT 1", "database": "secondary"}
            )
        assert response.status_code == 200
        engine.assert_called_with(name="secondary")
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

    async def test_preserves_selected_database_and_result_values(
        self, client: AsyncClient, db_session, sql_engine
    ):
        from langchain_core.messages import AIMessage

        db_session.add(SqlConnection(name="secondary", owner_id=LEGACY_ACCOUNT_ID))
        await db_session.commit()
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
        with (
            patch("app.api.routes.sql.sql_agent_node", AsyncMock(return_value=result)) as agent,
            patch("app.services.database._sql_engines", {"secondary": sql_engine}),
        ):
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

    async def test_connection_registry_is_account_private(self, client: AsyncClient, db_session, sql_engine):
        db_session.add(SqlConnection(name="private_db", owner_id="different-account"))
        await db_session.commit()
        with patch("app.services.database._sql_engines", {"private_db": sql_engine}):
            listed = await client.get("/api/v1/sql/connections")
            schema = await client.get("/api/v1/sql/schema?database=private_db")
            direct_tool = await client.post(
                "/api/v1/tools/execute",
                json={
                    "tool_name": "sql_query_tool",
                    "arguments": {"sql": "SELECT 1", "database": "private_db"},
                },
            )
        assert listed.json() == []
        assert schema.status_code == 404
        assert direct_tool.status_code == 404

    async def test_register_connection_claims_name_for_current_account(
        self, client: AsyncClient, db_session, sql_engine
    ):
        with patch("app.services.database.get_sql_engine", return_value=sql_engine) as create:
            response = await client.post(
                "/api/v1/sql/connections",
                json={"name": "reports", "url": "sqlite+aiosqlite:///reports.db"},
            )
        assert response.status_code == 200
        create.assert_called_once_with(
            database_url="sqlite+aiosqlite:///reports.db", name="reports"
        )
        registry = await db_session.get(SqlConnection, "reports")
        assert registry is not None and registry.owner_id == LEGACY_ACCOUNT_ID

    async def test_cannot_register_the_application_database(self, client, tmp_path, monkeypatch):
        app_db = tmp_path / "application.db"
        monkeypatch.setattr(
            "app.api.routes.sql.settings.app_database_url",
            f"sqlite+aiosqlite:///{app_db}",
        )
        with patch("app.services.database.get_sql_engine") as create_engine:
            response = await client.post(
                "/api/v1/sql/connections",
                json={"name": "app-data", "url": f"sqlite:///{app_db}"},
            )

        assert response.status_code == 422
        create_engine.assert_not_called()
