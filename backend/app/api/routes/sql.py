"""SQL agent endpoints.

Provides:
    POST /sql/query          — Execute a natural language query via the SQL agent.
    POST /sql/execute        — Execute a raw SQL query directly (validated).
    GET  /sql/schema         — Get the database schema.
    POST /sql/connections    — Register a new database connection.
    GET  /sql/connections    — List registered database connections.
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from fastapi import APIRouter, Request

from app.agents.orchestrator import run_agent
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
    format_schema_for_prompt,
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

    Uses the orchestrator with forced SQL agent routing for explicit SQL requests.
    """
    start_time = time.perf_counter()

    # Run the orchestrator — the question will be classified as SQL
    result = await run_agent(
        user_input=body.question,
        conversation_id=f"sql-{int(time.time())}",
    )

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
            generated_sql = tc.get("tool_input", {}).get("query", "")
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
        validated_sql = validate_query(body.sql)
    except Exception as exc:
        raise InputValidationError(str(exc))

    try:
        result = await execute_query(validated_sql)
    except Exception as exc:
        from app.api.middleware.error_handler import SQLExecutionError

        raise SQLExecutionError(str(exc))

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
        schema = await introspect_schema()
    except Exception as exc:
        from app.api.middleware.error_handler import DatabaseConnectionError

        raise DatabaseConnectionError(str(exc))

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

        raise DatabaseConnectionError(str(exc))

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
    """Best-effort parsing of tool output to extract columns and rows.

    The sql_query_tool returns a formatted string. We attempt to parse
    it into structured data.
    """
    lines = output.strip().split("\n")
    if not lines:
        return {"columns": [], "rows": []}

    # Try to detect a table-like format (pipe-separated)
    for i, line in enumerate(lines):
        if "|" in line and not line.strip().startswith("-"):
            headers = [h.strip() for h in line.split("|") if h.strip()]
            data_rows = []
            for data_line in lines[i + 1 :]:
                if data_line.strip().startswith("-"):
                    continue
                if "|" in data_line:
                    row = [c.strip() for c in data_line.split("|") if c.strip()]
                    if row:
                        data_rows.append(row)
            if headers:
                return {"columns": headers, "rows": data_rows}

    return {"columns": [], "rows": []}
