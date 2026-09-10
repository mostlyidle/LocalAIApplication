"""SQL tools for schema introspection, query validation, and execution.

These tools are designed to be bound to the SQL Agent via llm.bind_tools().
They enforce read-only access by default, validate generated SQL for safety,
and automatically append LIMIT clauses to prevent unbounded result sets.
"""

from __future__ import annotations

import json
import time
from typing import Any

import sqlparse
import structlog
from langchain_core.tools import tool
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.error_handler import SQLExecutionError, UnsafeQueryError
from app.config import settings
from app.services.database import get_sql_engine

logger = structlog.get_logger(__name__)

# Keywords that indicate destructive SQL operations
FORBIDDEN_KEYWORDS: set[str] = {
    "DROP",
    "DELETE",
    "TRUNCATE",
    "ALTER",
    "INSERT",
    "UPDATE",
    "CREATE",
    "GRANT",
    "REVOKE",
    "REPLACE",
    "MERGE",
    "INTO",
}


def validate_query(sql: str, allow_writes: bool | None = None) -> str:
    """Validate and sanitize a SQL query before execution.

    Args:
        sql: The SQL query string to validate.
        allow_writes: Whether to permit write operations. Defaults to settings.

    Returns:
        The validated (and possibly amended) SQL string.

    Raises:
        UnsafeQueryError: If the query contains forbidden keywords in read-only mode.
    """
    writes_allowed = allow_writes if allow_writes is not None else settings.sql_allow_writes
    cleaned = sqlparse.format(sql, strip_comments=True).strip().rstrip(";").strip()

    parsed = sqlparse.parse(cleaned)
    if not parsed:
        raise UnsafeQueryError("Empty or unparsable SQL query.")
    if len(parsed) != 1:
        raise UnsafeQueryError("Only one SQL statement is allowed per query.")

    for statement in parsed:
        stmt_type = statement.get_type()
        if not writes_allowed and stmt_type and stmt_type.upper() != "SELECT":
            raise UnsafeQueryError(
                f"Only SELECT queries are allowed. Got: {stmt_type}. "
                "Enable write mode in settings to allow mutations."
            )

        # Check for forbidden keywords in the token stream
        if not writes_allowed:
            for token in statement.flatten():
                if token.ttype is not None and token.value.upper() in FORBIDDEN_KEYWORDS:
                    raise UnsafeQueryError(
                        f"Query contains forbidden keyword: {token.value.upper()}"
                    )

    # Inspect the outer statement, not strings, comments, or nested queries.
    statement = parsed[0]
    if statement.get_type() == "SELECT":
        limit_index = next(
            (
                index
                for index, token in enumerate(statement.tokens)
                if token.ttype in sqlparse.tokens.Keyword and token.normalized == "LIMIT"
            ),
            None,
        )
        if limit_index is None:
            cleaned = f"{cleaned} LIMIT {settings.sql_max_rows}"
        else:
            _, count = statement.token_next(limit_index)
            if not (
                count is not None
                and count.ttype in sqlparse.tokens.Number.Integer
                and 0 <= int(count.value) <= settings.sql_max_rows
            ):
                cleaned = (
                    f"SELECT * FROM ({cleaned}\n) AS limited_query LIMIT {settings.sql_max_rows}"
                )

    return cleaned + ";"


async def introspect_schema(database: str = "default") -> dict[str, Any]:
    """Introspect the target database schema.

    Returns a dict with table names, column names, types, PKs, and FKs.
    """
    engine = get_sql_engine(name=database)

    async with engine.connect() as conn:
        # Use run_sync because Inspector is synchronous
        def _inspect(sync_conn: Any) -> dict[str, Any]:
            insp = inspect(sync_conn)
            tables_info = []
            for table_name in insp.get_table_names():
                columns = []
                pk_cols = {
                    c for c in insp.get_pk_constraint(table_name).get("constrained_columns", [])
                }
                fk_map: dict[str, str] = {}
                for fk in insp.get_foreign_keys(table_name):
                    for col in fk.get("constrained_columns", []):
                        ref = f"{fk['referred_table']}.{fk['referred_columns'][0]}"
                        fk_map[col] = ref

                for col in insp.get_columns(table_name):
                    columns.append(
                        {
                            "name": col["name"],
                            "type": str(col["type"]),
                            "nullable": col.get("nullable", True),
                            "primary_key": col["name"] in pk_cols,
                            "foreign_key": fk_map.get(col["name"]),
                        }
                    )
                tables_info.append(
                    {
                        "name": table_name,
                        "columns": columns,
                    }
                )
            return {"database": database, "tables": tables_info}

        return await conn.run_sync(_inspect)


async def execute_query(
    sql: str,
    database: str = "default",
) -> dict[str, Any]:
    """Execute a validated SQL query and return results.

    Args:
        sql: The SQL query (should already be validated).
        database: Target database connection name.

    Returns:
        Dict with columns, rows, row_count, and execution_time_ms.

    Raises:
        SQLExecutionError: If the query fails at the DB level.
    """
    sql = validate_query(sql)
    engine = get_sql_engine(name=database)
    start = time.perf_counter()

    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            result = await session.execute(text(sql))
            columns = list(result.keys()) if result.returns_rows else []
            rows = (
                [list(row) for row in result.fetchmany(settings.sql_max_rows)]
                if result.returns_rows
                else []
            )
            duration_ms = (time.perf_counter() - start) * 1000

            logger.info(
                "sql_query_executed",
                database=database,
                row_count=len(rows),
                duration_ms=round(duration_ms, 2),
            )
            return {
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "execution_time_ms": round(duration_ms, 2),
            }
    except Exception as exc:
        logger.error("sql_execution_failed", error=str(exc), sql=sql[:200])
        raise SQLExecutionError(f"Query execution failed: {exc}") from exc


def format_schema_for_prompt(schema: dict[str, Any]) -> str:
    """Format database schema into a concise string for LLM system prompts."""
    lines = [f"Database: {schema['database']}", ""]
    for table in schema["tables"]:
        lines.append(f"Table: {table['name']}")
        for col in table["columns"]:
            pk = " [PK]" if col.get("primary_key") else ""
            fk = f" -> {col['foreign_key']}" if col.get("foreign_key") else ""
            null = "" if col.get("nullable", True) else " NOT NULL"
            lines.append(f"  {col['name']}: {col['type']}{pk}{fk}{null}")
        lines.append("")
    return "\n".join(lines)


# ── LangChain tool wrappers (for agent binding) ────────────────────────


@tool
async def sql_query_tool(
    sql: str,
    database: str = "default",
) -> str:
    """Execute a read-only SQL query against the database.

    The query is validated for safety before execution. Only SELECT queries
    are allowed unless write mode is enabled. A LIMIT clause is auto-appended
    if missing.

    Args:
        sql: The SQL SELECT query to execute.
        database: The database connection name (default: "default").

    Returns:
        JSON containing columns, typed rows, row count, and execution time.
    """
    validated = validate_query(sql)
    result = await execute_query(validated, database)

    return json.dumps(result, default=str)


@tool
async def sql_schema_tool(database: str = "default") -> str:
    """Get the database schema (tables, columns, types, keys).

    Use this tool to understand the database structure before writing queries.

    Args:
        database: The database connection name (default: "default").

    Returns:
        Human-readable schema description.
    """
    schema = await introspect_schema(database)
    return format_schema_for_prompt(schema)


@tool
async def sql_validate_tool(sql: str) -> str:
    """Validate a SQL query for safety without executing it.

    Checks for forbidden keywords, ensures it's a SELECT query,
    and auto-appends LIMIT if missing.

    Args:
        sql: The SQL query to validate.

    Returns:
        The validated/amended query, or an error message.
    """
    try:
        validated = validate_query(sql)
        return f"Valid query: {validated}"
    except UnsafeQueryError as exc:
        return f"UNSAFE: {exc.message}"


# All SQL tools for agent binding
sql_tools = [sql_query_tool, sql_schema_tool, sql_validate_tool]
