"""MCP Server for SQL database tools.

Exposes SQL query, schema introspection, and validation tools as an MCP
server using the FastMCP high-level API. Runs via stdio transport by default
for local tool access.

Usage:
    python -m app.mcp.servers.sql_server          # stdio (default)
    uvicorn app.mcp.servers.sql_server:mcp.app    # HTTP (if needed)
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from mcp.server.fastmcp import FastMCP

logger = structlog.get_logger(__name__)

sql_mcp = FastMCP(
    "SQL Tools",
    instructions="SQL database query, schema introspection, and validation tools.",
)


@sql_mcp.tool()
async def query_database(sql: str, database: str = "default") -> str:
    """Execute a read-only SQL query against the specified database.

    The query is validated for safety before execution — only SELECT queries
    are permitted by default. A LIMIT clause is auto-appended if missing.

    Args:
        sql: The SQL SELECT query to execute.
        database: The database connection name from configuration.
    """
    from app.tools.sql_tools import execute_query, validate_query

    try:
        validated = validate_query(sql, database=database)
    except Exception as exc:
        return f"Validation error: {exc}"

    try:
        result = await execute_query(validated, database)
    except Exception as exc:
        return f"Execution error: {exc}"

    if not result["rows"]:
        return "Query returned no results."

    header = " | ".join(str(c) for c in result["columns"])
    separator = "-" * len(header)
    rows_str = "\n".join(" | ".join(str(v) for v in row) for row in result["rows"][:50])
    truncated = f"\n... ({result['row_count']} total rows)" if result["row_count"] > 50 else ""
    return f"{header}\n{separator}\n{rows_str}{truncated}"


@sql_mcp.tool()
async def validate_sql(sql: str, database: str = "default") -> str:
    """Validate a SQL query for safety without executing it.

    Checks for forbidden keywords, ensures it's a SELECT query, and
    auto-appends LIMIT if missing.

    Args:
        sql: The SQL query to validate.
        database: Registered connection to validate against.
    """
    from app.tools.sql_tools import validate_query

    try:
        validated = validate_query(sql, database=database)
        return f"Valid query: {validated}"
    except Exception as exc:
        return f"UNSAFE: {exc}"


@sql_mcp.resource("schema://{database}")
async def get_schema(database: str) -> str:
    """Get the full schema of a database including tables, columns, types, and keys.

    Args:
        database: The database connection name (default: "default").
    """
    from app.tools.sql_tools import format_schema_for_prompt, introspect_schema

    try:
        schema = await introspect_schema(database)
        return format_schema_for_prompt(schema)
    except Exception as exc:
        return f"Schema introspection error: {exc}"


@sql_mcp.resource("connections://list")
async def list_connections() -> str:
    """List all registered database connections."""
    from app.services.database import _sql_engines

    connections = [
        {"name": name, "url": str(engine.url).split("@")[-1]}
        for name, engine in _sql_engines.items()
    ]
    return json.dumps(connections, indent=2)


if __name__ == "__main__":
    sql_mcp.run()
