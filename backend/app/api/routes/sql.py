"""SQL agent endpoints.

Provides:
    POST /sql/query          — Execute a natural language query via the SQL agent.
    POST /sql/execute        — Execute a raw SQL query directly (validated).
    GET  /sql/schema         — Get the database schema.
    POST /sql/connections    — Register a new database connection.
    GET  /sql/connections    — List registered database connections.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Request

from app.agents.sql_agent import sql_agent_node
from app.agents.state import create_initial_state
from app.api.middleware.error_handler import InputValidationError
from app.api.middleware.rate_limiting import limiter
from app.config import settings
from app.models.schemas import (
    DatabaseConnectionRequest,
    DatabaseSchema,
    SQLExecuteRequest,
    SQLQueryRequest,
    SQLQueryResult,
)
from app.tools.sql_tools import (
    execute_query,
    introspect_schema,
    validate_query,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# POST /sql/query — natural language to SQL via agent
# ---------------------------------------------------------------------------


@router.post("/sql/query", response_model=SQLQueryResult)
@limiter.limit(settings.rate_limit_llm)
async def natural_language_query(
    request: Request,
    body: SQLQueryRequest,
) -> SQLQueryResult:
    """Convert a natural language question to SQL, execute, and return results.

    Invokes the SQL specialist directly with the selected database connection.
    """
    start_time = time.perf_counter()

    # This endpoint is explicitly SQL; the user's selected connection is authoritative.
    state = create_initial_state(
        user_input=body.question,
        conversation_id=f"sql-{uuid.uuid4()}",
    )
    state["database"] = body.database
    result = await sql_agent_node(state)

    # Extract response and tool calls
    response_content = ""
    messages = result.get("messages", [])
    if messages:
        last_msg = messages[-1]
        if hasattr(last_msg, "content"):
            response_content = str(last_msg.content)

    # Find the executed SQL query and results from tool calls
    tool_calls = result.get("tool_calls", [])
    generated_sql = ""
    columns: list[str] = []
    rows: list[list[Any]] = []

    for tc in tool_calls:
        if tc.get("tool_name") == "sql_query_tool":
            generated_sql = tc.get("tool_input", {}).get("sql", "")
            # Parse the tool output for results
            output = tc.get("tool_output", "")
            parsed = _parse_query_output(output)
            columns = parsed.get("columns", [])
            rows = parsed.get("rows", [])

    elapsed_ms = (time.perf_counter() - start_time) * 1000

    return SQLQueryResult(
        question=body.question,
        generated_sql=generated_sql,
        columns=columns,
        rows=rows,
        row_count=len(rows),
        explanation=response_content,
        execution_time_ms=round(elapsed_ms, 2),
    )


# ---------------------------------------------------------------------------
# POST /sql/execute — raw SQL execution (validated)
# ---------------------------------------------------------------------------


@router.post("/sql/execute")
@limiter.limit(settings.rate_limit_llm)
async def execute_raw_query(
    request: Request,
    body: SQLExecuteRequest,
) -> dict[str, Any]:
    """Execute a raw SQL query (validated for safety) and return results.

    Only SELECT queries are allowed unless write mode is explicitly enabled.
    """
    start_time = time.perf_counter()

    try:
        validated_sql = validate_query(body.sql, database=body.database)
    except Exception as exc:
        raise InputValidationError(str(exc)) from exc

    try:
        result = await execute_query(validated_sql, database=body.database)
    except Exception as exc:
        from app.api.middleware.error_handler import SQLExecutionError

        raise SQLExecutionError(str(exc)) from exc

    elapsed_ms = (time.perf_counter() - start_time) * 1000

    return {
        "sql": validated_sql,
        "result": result,
        "execution_time_ms": round(elapsed_ms, 2),
    }


# ---------------------------------------------------------------------------
# GET /sql/schema — database schema introspection
# ---------------------------------------------------------------------------


@router.get("/sql/schema", response_model=DatabaseSchema)
async def get_schema(
    database: str = "default",
) -> DatabaseSchema:
    """Get the schema of the target database including tables, columns, and types."""
    try:
        schema = await introspect_schema(database=database)
    except Exception as exc:
        from app.api.middleware.error_handler import DatabaseConnectionError

        raise DatabaseConnectionError(str(exc)) from exc

    # Convert to response model
    from app.models.schemas import ColumnInfo, TableInfo

    tables = []
    for table_data in schema.get("tables", []):
        cols = [
            ColumnInfo(
                name=col.get("name", ""),
                type=col.get("type", ""),
                nullable=col.get("nullable", True),
                primary_key=col.get("primary_key", False),
                foreign_key=col.get("foreign_key"),
            )
            for col in table_data.get("columns", [])
        ]
        tables.append(TableInfo(name=table_data.get("name", ""), columns=cols))

    return DatabaseSchema(database=database, tables=tables)


# ---------------------------------------------------------------------------
# POST /sql/connections — register a new DB connection
# ---------------------------------------------------------------------------


@router.post("/sql/connections")
async def register_connection(
    request: DatabaseConnectionRequest,
) -> dict[str, str]:
    """Register a new database connection for the SQL agent.

    The connection URL is stored in the engine cache. To persist across
    restarts, update the environment configuration.
    """
    from app.services.database import get_sql_engine

    try:
        get_sql_engine(database_url=request.url, name=request.name)
    except Exception as exc:
        from app.api.middleware.error_handler import DatabaseConnectionError

        raise DatabaseConnectionError(str(exc)) from exc

    logger.info("sql_connection_registered", name=request.name)
    return {"status": "connected", "name": request.name}


# ---------------------------------------------------------------------------
# GET /sql/connections — list registered connections
# ---------------------------------------------------------------------------


@router.get("/sql/connections")
async def list_connections() -> list[dict[str, str]]:
    """List all registered database connections."""
    from app.services.database import _sql_engines

    return [
        {"name": name, "url": str(engine.url).split("@")[-1]}
        for name, engine in _sql_engines.items()
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_query_output(output: str) -> dict[str, Any]:
    """Read structured query output without losing nulls, types, or delimiters."""
    try:
        result = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return {"columns": [], "rows": []}
    if isinstance(result, dict):
        return {"columns": result.get("columns", []), "rows": result.get("rows", [])}
    return {"columns": [], "rows": []}
