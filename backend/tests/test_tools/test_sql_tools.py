"""Tests for app.tools.sql_tools."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest

from app.api.middleware.error_handler import SQLExecutionError, UnsafeQueryError
from app.tools.sql_tools import (
    _execute_with_deadline,
    execute_query,
    format_schema_for_prompt,
    introspect_schema,
    validate_query,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

# =============================================================================
# validate_query — synchronous, pure function
# =============================================================================


class TestValidateQuery:
    """Tests for SQL query validation and sanitisation."""

    @pytest.mark.parametrize(
        "sql",
        [
            "WITH changed AS (DELETE FROM users RETURNING *) SELECT * FROM changed",
            "SELECT * FROM users FOR UPDATE",
            "SELECT * FROM users INTO OUTFILE '/tmp/copied'",
        ],
    )
    def test_rejects_nested_writes_and_side_effects(self, sql: str) -> None:
        with pytest.raises(UnsafeQueryError):
            validate_query(sql, dialect="postgres")

    def test_quoted_keywords_are_data(self) -> None:
        result = validate_query("SELECT 'DROP' AS label, \"DELETE\" FROM users", dialect="sqlite")
        assert "'DROP'" in result
        assert '"DELETE"' in result

    @pytest.mark.parametrize(
        ("dialect", "sql", "expected"),
        [
            ("mssql", "SELECT * FROM users", "TOP 100"),
            ("oracle", "SELECT * FROM users", "FETCH FIRST 100 ROWS ONLY"),
            ("postgresql", "SELECT * FROM users LIMIT 1000", "LIMIT 100"),
            ("mysql", "SELECT * FROM users LIMIT 10, 1000", "LIMIT 100 OFFSET 10"),
            ("tsql", "SELECT TOP 1 PERCENT * FROM users", "TOP 100"),
            ("oracle", "SELECT * FROM users FETCH FIRST 10 ROWS ONLY", "FETCH FIRST 10"),
        ],
    )
    def test_dialect_row_limits(self, dialect: str, sql: str, expected: str) -> None:
        assert expected in validate_query(sql, dialect=dialect)

    def test_union_gets_outer_limit(self) -> None:
        result = validate_query("SELECT 1 UNION ALL SELECT 2", dialect="sqlite")
        assert result.endswith("LIMIT 100;")

    @pytest.mark.parametrize(
        "expression",
        [
            "CAST('2000-01-01' AS DATE)",
            "CAST(CAST('2000-01-01' AS DATE) AS TEXT)",
            "CAST('1.5' AS BOOLEAN)",
            "CAST('1' AS DECIMAL)",
            "CAST('12' AS BINARY)",
            "DATE('2000-01-01')",
        ],
    )
    def test_preserves_sqlite_cast_results(self, expression: str) -> None:
        sql = f"SELECT {expression} AS value"
        validated = validate_query(sql, dialect="sqlite")
        connection = sqlite3.connect(":memory:")
        try:
            expected = connection.execute(sql).fetchone()[0]
            actual = connection.execute(validated).fetchone()[0]
            assert actual == expected
            assert type(actual) is type(expected)
        finally:
            connection.close()

    @pytest.mark.parametrize("sql", ["SELECT 1; SELECT 2", "SELECT * INTO copy FROM users"])
    def test_rejects_multiple_statements_and_select_into(self, sql):
        with pytest.raises(UnsafeQueryError):
            validate_query(sql)

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

    async def test_execution_timeout(self, sql_engine) -> None:
        async def slow_execute(*args: Any, **kwargs: Any) -> None:
            await asyncio.sleep(1)

        session = AsyncMock()
        session.__aenter__.return_value = session
        session.execute.side_effect = slow_execute
        driver_connection = SimpleNamespace(interrupt=AsyncMock())
        raw_connection = SimpleNamespace(driver_connection=driver_connection)
        async_connection = SimpleNamespace(
            get_raw_connection=AsyncMock(return_value=raw_connection)
        )
        session.connection = AsyncMock(return_value=async_connection)
        with (
            patch("app.tools.sql_tools.get_sql_engine", return_value=sql_engine),
            patch("app.tools.sql_tools.AsyncSession", return_value=session),
            patch("app.tools.sql_tools.settings.sql_query_timeout_seconds", 0.01),
            pytest.raises(SQLExecutionError, match="timed out"),
        ):
            await execute_query("SELECT 1")
        driver_connection.interrupt.assert_awaited_once()

    async def test_query_task_is_settled_when_caller_cancels(self) -> None:
        started = asyncio.Event()
        finished = asyncio.Event()
        query_task: asyncio.Task[None] | None = None

        async def slow_execute(*args: Any, **kwargs: Any) -> None:
            nonlocal query_task
            query_task = asyncio.current_task()
            started.set()
            try:
                await asyncio.sleep(30)
            finally:
                finished.set()

        session = SimpleNamespace(execute=slow_execute)
        driver_connection = SimpleNamespace(interrupt=AsyncMock())
        deadline_task = asyncio.create_task(
            _execute_with_deadline(session, "SELECT 1", 30, driver_connection)
        )
        await started.wait()
        deadline_task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await deadline_task
        await asyncio.wait_for(finished.wait(), timeout=1)
        assert query_task is not None and query_task.done()
        driver_connection.interrupt.assert_awaited_once()

    async def test_sqlite_timeout_interrupts_a_running_driver_query(
        self, sql_engine: AsyncEngine
    ) -> None:
        query = (
            "WITH RECURSIVE cnt(x) AS (VALUES(0) "
            "UNION ALL SELECT x + 1 FROM cnt WHERE x < 10000000) "
            "SELECT SUM(x) FROM cnt"
        )
        started = time.perf_counter()
        with (
            patch("app.tools.sql_tools.get_sql_engine", return_value=sql_engine),
            patch("app.tools.sql_tools.settings.sql_query_timeout_seconds", 0.01),
            pytest.raises(SQLExecutionError, match="timed out"),
        ):
            await execute_query(query)

        assert time.perf_counter() - started < 1

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM users",
            "SELECT 'LIMIT' AS label, id FROM users",
            "SELECT * FROM users -- trailing comment",
            "SELECT * FROM users LIMIT -1",
            "SELECT * FROM users LIMIT 1000",
            "SELECT * FROM users LIMIT 0, 1000",
            "SELECT * FROM users WHERE id IN (SELECT id FROM users LIMIT 1000)",
        ],
    )
    async def test_enforces_limit_at_execution_boundary(self, sql_engine, sql):
        with (
            patch("app.tools.sql_tools.get_sql_engine", return_value=sql_engine),
            patch("app.tools.sql_tools.settings.sql_max_rows", 2),
        ):
            result = await execute_query(sql)
        assert result["row_count"] == 2

    async def test_execution_rejects_writes_without_prior_validation(self, sql_engine):
        with (
            patch("app.tools.sql_tools.get_sql_engine", return_value=sql_engine),
            pytest.raises(UnsafeQueryError),
        ):
            await execute_query("DELETE FROM users")

    async def test_write_mode_commits_successful_statements(self, sql_engine):
        with (
            patch("app.tools.sql_tools.get_sql_engine", return_value=sql_engine),
            patch("app.tools.sql_tools.settings.sql_allow_writes", True),
        ):
            await execute_query(
                "INSERT INTO users (name, email, age) VALUES ('Eve', 'eve@test.com', 22)"
            )
            result = await execute_query("SELECT name FROM users WHERE email = 'eve@test.com'")

        assert result["rows"] == [["Eve"]]

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
        with patch("app.tools.sql_tools.get_sql_engine", return_value=sql_engine), pytest.raises(
            SQLExecutionError
        ):
            await execute_query("SELECT * FROM nonexistent_table;")
