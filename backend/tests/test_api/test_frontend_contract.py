"""Validate real HTTP response bodies with the frontend's runtime schemas."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, Response
from langchain_core.messages import AIMessage

from app.dependencies import get_vector_store
from app.models.db_models import Document
from app.models.enums import DocumentFormat, DocumentStatus

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession


async def test_http_responses_pass_frontend_schemas(
    client: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Exercise both sides of the contract; UI-shaped fetch mocks cannot hide drift."""
    frontend = Path(__file__).resolve().parents[3] / "frontend"
    node = shutil.which("node")
    if node is None or not (frontend / "node_modules/typescript").exists():
        pytest.skip("Contract checks require Node and installed frontend dependencies")

    path = tmp_path / "contract.txt"
    path.write_text("A local contract document.", encoding="utf-8")
    doc = Document(
        id="contract-doc",
        filename=path.name,
        format=DocumentFormat.from_extension(".txt"),
        size_bytes=26,
        storage_path=str(path),
        status=DocumentStatus.PENDING,
    )
    db_session.add(doc)
    await db_session.commit()
    store = AsyncMock()
    store.list_collections.return_value = [{"name": "documents", "document_count": 1}]
    store.search.return_value = [
        {
            "content": "A local contract document.",
            "score": 0.9,
            "metadata": {"source": path.name},
        }
    ]
    store.search_with_provenance.return_value = SimpleNamespace(
        passages=store.search.return_value,
        retrieval={"mode": "hybrid_rrf", "strategy": "hybrid_rrf"},
    )
    store.add_documents.return_value = 1
    app.dependency_overrides[get_vector_store] = lambda: store
    query_result = {"columns": ["value"], "rows": [[1]], "row_count": 1, "execution_time_ms": 0.1}
    agent_result = {
        "messages": [AIMessage(content="One result.")],
        "metadata": {"agent_used": "sql"},
        "tool_calls": [
            {
                "tool_name": "sql_query_tool",
                "tool_input": {"sql": "SELECT 1"},
                "tool_output": json.dumps(query_result),
            }
        ],
    }
    samples = []
    requests = [
        ("GET", "/documents", None, "documentListSchema"),
        ("POST", "/documents/contract-doc/analyze", None, "analysisResultSchema"),
        ("POST", "/chat", {"content": "Hello"}, "chatResponseSchema"),
        ("GET", "/chat/conversations", None, "conversationsListSchema"),
        ("GET", "/sql/connections", None, "sqlConnectionsSchema"),
        ("POST", "/sql/query", {"question": "Count rows"}, "sqlQueryResponseSchema"),
        ("POST", "/sql/execute", {"sql": "SELECT 1"}, "sqlExecuteResponseSchema"),
        ("GET", "/tools", None, "toolsListSchema"),
        ("GET", "/rag/collections", None, "ragCollectionsSchema"),
        ("POST", "/rag/search", {"query": "local"}, "ragSearchResultSchema"),
        ("POST", "/rag/ingest", {"document_id": doc.id}, "ragIngestSchema"),
    ]
    with (
        patch("app.api.routes.chat.run_agent", AsyncMock(return_value=agent_result)),
        patch("app.api.routes.sql.sql_agent_node", AsyncMock(return_value=agent_result)),
        patch("app.api.routes.sql.execute_query", AsyncMock(return_value=query_result)),
    ):
        for method, route, body, schema in requests:
            response = await client.request(method, f"/api/v1{route}", json=body)
            assert response.status_code == 200, (route, response.text)
            samples.append({"route": route, "schema": schema, "body": response.json()})

    # Exercise the actual health route with only external providers replaced.
    ollama = AsyncMock()
    ollama.__aenter__.return_value.get.return_value = Response(200, json={"models": []})
    with (
        patch(
            "app.services.transcription.check_local_asr_readiness",
            AsyncMock(return_value=(False, "Not configured")),
        ),
        patch(
            "app.services.hybrid_vector_store.hybrid_vector_store_service.list_collections",
            store.list_collections,
        ),
        patch("app.services.database.get_app_engine", return_value=db_session.bind),
        patch("app.api.routes.tools.httpx.AsyncClient", return_value=ollama),
    ):
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        samples.append({"route": "/health", "schema": "healthSchema", "body": response.json()})

    javascript = """
const fs = require('fs'), ts = require('typescript');
const mod = {exports: {}};
const source = ts.transpileModule(fs.readFileSync('src/lib/schemas.ts', 'utf8'), {
  compilerOptions: {module: ts.ModuleKind.CommonJS},
}).outputText;
new Function('require', 'module', 'exports', source)(require, mod, mod.exports);
let input = '';
process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', () => {
  for (const sample of JSON.parse(input)) {
    const result = mod.exports[sample.schema].safeParse(sample.body);
    if (!result.success) {
      console.error(sample.route, result.error.message);
      process.exitCode = 1;
    }
  }
});
"""
    process = await asyncio.create_subprocess_exec(
        node,
        "-e",
        javascript,
        cwd=frontend,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, errors = await asyncio.wait_for(
            process.communicate(json.dumps(samples).encode()),
            timeout=20,
        )
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise
    assert process.returncode == 0, errors.decode()
