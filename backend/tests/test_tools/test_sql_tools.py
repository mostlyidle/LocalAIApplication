"""Tests for app.tools.sql_tools."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from app.api.middleware.error_handler import UnsafeQueryError
from app.tools.sql_tools import (
    execute_query,
    format_schema_for_prompt,
    introspect_schema,
    validate_query,
)


# =============================================================================
# validate_query — synchronous, pure function
# =============================================================================


class TestValidateQuery:
    """Tests for SQL query validation and sanitisation."""

    # -- Safe SELECT queries -----------------------------------------------

    def test_simple_select(self):
        result = validate_query("SELECT * FROM users")
        assert result.strip().endswith(";")
        assert "SELECT" in result

    def test_select_with_where(self):
        result = validate_query("SELECT name FROM users WHERE age > 30")
        assert "WHERE" in result

    def test_auto_appends_limit(self):
        result = validate_query("SELECT * FROM users")
        assert "LIMIT" in result.upper()

    def test_preserves_existing_limit(self):
        result = validate_query("SELECT * FROM users LIMIT 10")
        # Should NOT double-add a LIMIT
        assert result.upper().count("LIMIT") == 1

    def test_semicolon_handling(self):
        result = validate_query("SELECT 1;")
        assert result.endswith(";")

    # -- Unsafe queries (read-only mode) -----------------------------------

    def test_rejects_drop(self):
        with pytest.raises(UnsafeQueryError):
            validate_query("DROP TABLE users")

    def test_rejects_delete(self):
        with pytest.raises(UnsafeQueryError):
            validate_query("DELETE FROM users WHERE id = 1")

    def test_rejects_insert(self):
        with pytest.raises(UnsafeQueryError):
            validate_query("INSERT INTO users (name) VALUES ('hacker')")

    def test_rejects_update(self):
        with pytest.raises(UnsafeQueryError):
            validate_query("UPDATE users SET name = 'hacked'")

    def test_rejects_truncate(self):
        with pytest.raises(UnsafeQueryError):
            validate_query("TRUNCATE TABLE users")

    def test_rejects_alter(self):
        with pytest.raises(UnsafeQueryError):
            validate_query("ALTER TABLE users ADD COLUMN hacked TEXT")

    def test_rejects_create(self):
        with pytest.raises(UnsafeQueryError):
            validate_query("CREATE TABLE evil (id INT)")

    def test_rejects_grant(self):
        with pytest.raises(UnsafeQueryError):
            validate_query("GRANT ALL ON users TO hacker")

    # -- Write mode --------------------------------------------------------

    def test_allows_insert_with_write_mode(self):
        result = validate_query("INSERT INTO users (name) VALUES ('test')", allow_writes=True)
        assert "INSERT" in result.upper()

    # -- Edge cases --------------------------------------------------------

    def test_empty_query(self):
        with pytest.raises(UnsafeQueryError, match="Empty or unparsable"):
            validate_query("")

    def test_whitespace_only(self):
        with pytest.raises(UnsafeQueryError, match="Empty or unparsable"):
            validate_query("   ")


# =============================================================================
# format_schema_for_prompt — pure function
# =============================================================================


class TestFormatSchemaForPrompt:
    """Tests for the schema-to-prompt formatter."""

    def test_basic_formatting(self):
        schema: dict[str, Any] = {
            "database": "test",
            "tables": [
                {
                    "name": "users",
                    "columns": [
                        {
                            "name": "id",
                            "type": "INTEGER",
                            "primary_key": True,
                            "nullable": False,
                            "foreign_key": None,
                        },
                        {
                            "name": "name",
                            "type": "VARCHAR(255)",
                            "primary_key": False,
                            "nullable": False,
                            "foreign_key": None,
                        },
                        {
                            "name": "team_id",
                            "type": "INTEGER",
                            "primary_key": False,
                            "nullable": True,
                            "foreign_key": "teams.id",
                        },
                    ],
                }
            ],
        }

        result = format_schema_for_prompt(schema)

        assert "Database: test" in result
        assert "Table: users" in result
        assert "[PK]" in result
        assert "NOT NULL" in result
        assert "-> teams.id" in result

    def test_empty_tables(self):
        schema: dict[str, Any] = {"database": "empty", "tables": []}
        result = format_schema_for_prompt(schema)
        assert "Database: empty" in result


# =============================================================================
# introspect_schema — async, requires a real engine
# =============================================================================


class TestIntrospectSchema:
    """Tests for async schema introspection against a real SQLite database."""

    async def test_returns_table_names(self, sql_engine):
        """Introspect a test database and verify we get the users table."""
        with patch("app.tools.sql_tools.get_sql_engine", return_value=sql_engine):
            schema = await introspect_schema(database="default")

        assert schema["database"] == "default"
        assert len(schema["tables"]) >= 1

        table_names = [t["name"] for t in schema["tables"]]
        assert "users" in table_names

    async def test_returns_columns(self, sql_engine):
        """Verify column metadata for the users table."""
        with patch("app.tools.sql_tools.get_sql_engine", return_value=sql_engine):
            schema = await introspect_schema(database="default")

        users_table = next(t for t in schema["tables"] if t["name"] == "users")
        col_names = [c["name"] for c in users_table["columns"]]
        assert "id" in col_names
        assert "name" in col_names
        assert "email" in col_names
        assert "age" in col_names


# =============================================================================
# execute_query — async, requires a real engine
# =============================================================================


class TestExecuteQuery:
    """Tests for executing SQL against the test database."""

    async def test_select_all(self, sql_engine):
        with patch("app.tools.sql_tools.get_sql_engine", return_value=sql_engine):
            result = await execute_query("SELECT * FROM users;")

        assert result["row_count"] == 3
        assert "id" in result["columns"]
        assert "name" in result["columns"]
        assert result["execution_time_ms"] >= 0

    async def test_select_with_filter(self, sql_engine):
        with patch("app.tools.sql_tools.get_sql_engine", return_value=sql_engine):
            result = await execute_query("SELECT name FROM users WHERE age > 28;")

        assert result["row_count"] == 2
        names = [row[0] for row in result["rows"]]
        assert "Alice" in names
        assert "Charlie" in names

    async def test_bad_query_raises(self, sql_engine):
        from app.api.middleware.error_handler import SQLExecutionError

        with patch("app.tools.sql_tools.get_sql_engine", return_value=sql_engine):
            with pytest.raises(SQLExecutionError):
                await execute_query("SELECT * FROM nonexistent_table;")
