# AGENTS.md — Local AI Application

## Persona

You are a senior software engineer. Generate production-ready code that is correct, efficient, secure, and maintainable.

### Code Quality Requirements

1. Follow language-specific best practices and idiomatic patterns, and strictly match the existing code style, architecture, and formatting of the surrounding codebase.
2. Implement robust error handling using appropriate mechanisms for the language (e.g., exceptions, result types, validation layers, logging). Errors must be meaningful, actionable, and must not leak sensitive information.
3. Anticipate and safely handle edge cases, invalid inputs, null/undefined states, concurrency issues, and resource management concerns.
4. Optimize performance where appropriate, avoiding premature optimization and unnecessary complexity.
5. Ensure readability and maintainability through clear structure, meaningful naming, modular design, and concise comments where necessary.
6. Address security concerns, including input validation, injection risks, overflow risks, authentication/authorization boundaries, and safe handling of sensitive data.
7. After implementing every feature, review the feature's diff against the request and surrounding code before declaring it complete. Check for correctness, regressions, security issues, and missing verification; fix issues introduced by the feature and review any resulting changes. In the completion response, report remaining findings or explicitly state that the review found none.

After generating code, briefly explain design decisions, trade-offs, assumptions, potential failure points, and possible improvements.

## Implementation Loop

For each feature or bug fix, repeat this loop until the requested behavior works and the review is clear:

1. **Define** the observable success criteria and inspect the affected code, callers, and existing checks.
2. **Reproduce** the reported failure with the smallest reliable case. For new behavior, define a checkable acceptance case. Keep secrets and personal data out of logs and fixtures.
3. **Diagnose** failures by listing plausible causes and testing one at a time; keep the original failing case available as a regression check.
4. **Implement** the smallest complete change that satisfies the success criteria and matches local patterns.
5. **Verify** the original case and the narrowest relevant regression checks. For model-backed features, check that the prompt, parser, and validator agree on the output contract, and cover valid plus malformed or incomplete output. Run broader checks when the change could affect them; report any checks that could not run.
6. **Review** the full diff against the request and surrounding code for correctness, regressions, security, and missing coverage. Fix each finding, then rerun the affected checks and review the new diff.
7. **Complete** only when the success criteria pass, relevant review findings are resolved, and the final report names the checks run and remaining risks.

---

## Project Overview

A **fully local, free, production-grade AI application** that runs entirely on Apple Silicon Macs using open-source models via Ollama. The application provides:

- **Document Intelligence**: Parse, analyze, and extract structured data from PDFs, images, Office documents, CSVs, HTML, and Markdown.
- **SQL Agent**: Natural language to SQL — formulate, validate, execute queries against any SQLAlchemy-supported database, and return formatted results.
- **RAG (Retrieval-Augmented Generation)**: Embed documents into a local vector store and perform semantic search for grounded, cited responses.
- **MCP Integration**: Expose application tools as MCP servers and consume external community MCP servers for extensibility.
- **Multi-modal Chat**: Conversational interface supporting text and image inputs with streaming responses.
- **Web Research Agent**: Scrape and summarize web content locally without API keys.

**Zero cloud dependencies. Zero API keys. Fully offline-capable.**

---

## Architecture

### System Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Next.js Frontend (Port 3000)              │
│  ┌──────────┐ ┌──────────────┐ ┌─────────┐ ┌────────────┐  │
│  │   Chat   │ │  Documents   │ │   SQL   │ │  Settings  │  │
│  └────┬─────┘ └──────┬───────┘ └────┬────┘ └─────┬──────┘  │
│       └──────────────┼──────────────┼─────────────┘         │
│                      │ REST + WebSocket                      │
└──────────────────────┼───────────────────────────────────────┘
                       │
┌──────────────────────┼───────────────────────────────────────┐
│              FastAPI Backend (Port 8000)                      │
│  ┌───────────────────┴────────────────────────┐              │
│  │           LangGraph Orchestrator            │              │
│  │  ┌────────────┐ ┌───────────┐ ┌──────────┐│              │
│  │  │ Chat Agent │ │ SQL Agent │ │ Doc Agent ││              │
│  │  └─────┬──────┘ └─────┬─────┘ └─────┬────┘│              │
│  │  ┌─────┴──────┐ ┌─────┴─────┐ ┌─────┴────┐│              │
│  │  │ RAG Agent  │ │ Web Agent │ │ MCP Tools ││              │
│  │  └────────────┘ └───────────┘ └───────────┘│              │
│  └─────────────────────────────────────────────┘              │
│       │            │             │                            │
│  ┌────┴────┐  ┌────┴─────┐  ┌───┴──────┐                    │
│  │ Ollama  │  │ Qdrant  │  │SQLAlchemy│                    │
│  │ Client  │  │ (Vector) │  │  (SQL)   │                    │
│  └────┬────┘  └──────────┘  └──────────┘                    │
└───────┼──────────────────────────────────────────────────────┘
        │
┌───────┴──────────────────────────────────────────────────────┐
│                  Ollama (Port 11434)                          │
│ Chat: llama3.1:8b, qwen2.5:7b, qwen2.5-coder:7b           │
│ Vision: qwen3-vl:4b, Laya: laya:latest                    │
│ Embeddings: nomic-embed-text                              │
│              Metal-accelerated on Apple Silicon               │
└──────────────────────────────────────────────────────────────┘
```

### Tech Stack

| Layer              | Technology                              | Version     |
|--------------------|-----------------------------------------|-------------|
| LLM Runtime        | Ollama                                  | latest      |
| Chat Models        | `llama3.1:8b`, `qwen2.5:7b`, `qwen2.5-coder:7b` | — |
| Vision Model       | `qwen3-vl:4b`                           | —           |
| Embedding Model    | `nomic-embed-text`                      | —           |
| RAG decision model | `laya:latest`                            | —           |
| Agent Framework    | LangGraph + LangChain                   | >=0.2       |
| MCP SDK            | `mcp` (FastMCP)                         | >=1.0       |
| Backend            | FastAPI                                 | >=0.115     |
| Frontend           | Next.js (App Router) + TypeScript       | 16.x        |
| UI Components      | shadcn/ui + Tailwind CSS                | 4.x         |
| Vector Store       | Qdrant + FastEmbed BM25 (hybrid RRF)    | pinned      |
| SQL Abstraction    | SQLAlchemy                              | >=2.0       |
| Document Parsing   | Unstructured + PyMuPDF + python-docx    | latest      |
| OCR                | EasyOCR or Surya                        | latest      |
| Package Manager    | `uv` (Python), `pnpm` (Node.js)        | latest      |

---

## Directory Structure

```
LocalAIApplication/
├── AGENTS.md
├── Makefile
├── docker-compose.yml          # Ollama, Qdrant, app, optional observability
├── .env.example
├── .gitignore
│
├── backend/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── alembic/                # Database migrations
│   │   └── versions/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py             # FastAPI application factory
│   │   ├── config.py           # pydantic-settings configuration
│   │   ├── dependencies.py     # FastAPI dependency injection
│   │   │
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── routes/
│   │   │   │   ├── chat.py         # POST /chat, WS /chat/stream
│   │   │   │   ├── documents.py    # POST /documents/upload, /documents/analyze
│   │   │   │   ├── sql.py          # POST /sql/query, GET /sql/schema
│   │   │   │   ├── rag.py          # POST /rag/search, /rag/ingest
│   │   │   │   └── tools.py        # GET /tools, POST /tools/execute
│   │   │   └── middleware/
│   │   │       ├── error_handler.py
│   │   │       ├── cors.py
│   │   │       └── request_logging.py
│   │   │
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── orchestrator.py     # LangGraph supervisor/router
│   │   │   ├── chat_agent.py       # General conversational agent
│   │   │   ├── sql_agent.py        # Text-to-SQL agent
│   │   │   ├── document_agent.py   # Document analysis agent
│   │   │   ├── rag_agent.py        # RAG retrieval agent
│   │   │   ├── web_agent.py        # Web research agent
│   │   │   └── state.py            # Shared agent state schema
│   │   │
│   │   ├── tools/
│   │   │   ├── __init__.py
│   │   │   ├── sql_tools.py        # Schema introspect, query build, execute
│   │   │   ├── document_tools.py   # Parse, OCR, extract tables/forms
│   │   │   ├── rag_tools.py        # Embed, search, retrieve
│   │   │   ├── web_tools.py        # Fetch URL, scrape, summarize
│   │   │   ├── filesystem_tools.py # Read/list files
│   │   │   └── calculator_tools.py # Math operations
│   │   │
│   │   ├── mcp/
│   │   │   ├── __init__.py
│   │   │   ├── servers/
│   │   │   │   ├── sql_server.py       # MCP server: SQL tools
│   │   │   │   ├── document_server.py  # MCP server: document tools
│   │   │   │   └── rag_server.py       # MCP server: RAG tools
│   │   │   └── client.py              # MCP client for external servers
│   │   │
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── llm.py             # Ollama client (ChatOllama wrapper)
│   │   │   ├── embeddings.py      # OllamaEmbeddings wrapper
│   │   │   ├── vector_store.py    # Qdrant hybrid retrieval boundary
│   │   │   ├── document_parser.py # Multi-format parsing pipeline
│   │   │   ├── ocr.py             # OCR engine abstraction
│   │   │   └── database.py        # SQLAlchemy engine/session factory
│   │   │
│   │   └── models/
│   │       ├── __init__.py
│   │       ├── schemas.py         # Pydantic request/response schemas
│   │       ├── db_models.py       # SQLAlchemy ORM models
│   │       └── enums.py           # Shared enumerations
│   │
│   └── tests/
│       ├── conftest.py
│       ├── test_agents/
│       ├── test_tools/
│       ├── test_services/
│       └── test_api/
│
├── frontend/
│   ├── package.json
│   ├── pnpm-lock.yaml
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   ├── components.json           # shadcn/ui config
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx          # Dashboard
│   │   │   ├── chat/
│   │   │   │   └── page.tsx      # Chat interface
│   │   │   ├── documents/
│   │   │   │   └── page.tsx      # Document upload & analysis
│   │   │   ├── sql/
│   │   │   │   └── page.tsx      # SQL agent interface
│   │   │   └── settings/
│   │   │       └── page.tsx      # Model, DB, MCP configuration
│   │   │
│   │   ├── components/
│   │   │   ├── chat/
│   │   │   │   ├── ChatWindow.tsx
│   │   │   │   ├── MessageBubble.tsx
│   │   │   │   ├── StreamingText.tsx
│   │   │   │   └── ToolCallDisplay.tsx
│   │   │   ├── documents/
│   │   │   │   ├── DocumentUploader.tsx
│   │   │   │   ├── DocumentViewer.tsx
│   │   │   │   └── ExtractionResults.tsx
│   │   │   ├── sql/
│   │   │   │   ├── QueryEditor.tsx
│   │   │   │   ├── ResultsTable.tsx
│   │   │   │   └── SchemaBrowser.tsx
│   │   │   └── shared/
│   │   │       ├── AppSidebar.tsx
│   │   │       ├── Header.tsx
│   │   │       └── ThemeProvider.tsx
│   │   │
│   │   ├── hooks/
│   │   │   ├── useChat.ts
│   │   │   ├── useWebSocket.ts
│   │   │   └── useDocuments.ts
│   │   │
│   │   ├── lib/
│   │   │   ├── api.ts            # Typed fetch wrapper
│   │   │   ├── utils.ts
│   │   │   └── constants.ts
│   │   │
│   │   └── types/
│   │       ├── chat.ts
│   │       ├── document.ts
│   │       └── sql.ts
│   │
│   └── tests/
│
└── scripts/
    ├── setup.sh                  # Full setup: install deps, pull models
    └── seed_demo_db.py           # Create demo SQLite DB with sample data
```

---

## Coding Standards

### Python (Backend)

- **Python 3.12+** required.
- Use `uv` as the package manager. All dependencies in `pyproject.toml`.
- **Type hints on all function signatures**. Use `from __future__ import annotations` in every module.
- Use `pydantic` v2 for all data validation — request/response schemas, config, agent state.
- Use `async def` for all I/O-bound operations (API routes, database queries, LLM calls, file reads).
- Use `structlog` for structured logging. Log at appropriate levels: `debug` for internals, `info` for operations, `warning` for recoverable issues, `error` for failures.
- Imports: standard library, then third-party, then local, separated by blank lines. Use absolute imports.
- Prefer composition over inheritance. Use dependency injection via FastAPI `Depends()`.
- Maximum line length: 100 characters. Use `ruff` for linting and formatting.
- Docstrings: Google style for all public functions and classes.
- No bare `except:`. Always catch specific exceptions. Always log tracebacks for unexpected errors.

```python
# Good
async def parse_document(file: UploadFile, parser: DocumentParser = Depends()) -> ParseResult:
    """Parse an uploaded document and extract structured content.

    Args:
        file: The uploaded file to parse.
        parser: Injected document parsing service.

    Returns:
        Parsed document with extracted text, tables, and metadata.

    Raises:
        DocumentParseError: If the file format is unsupported or corrupted.
    """
    if file.size > settings.max_upload_size_bytes:
        raise DocumentTooLargeError(max_size=settings.max_upload_size_bytes)
    ...
```

### TypeScript (Frontend)

- **TypeScript strict mode** enabled. No `any` types unless truly unavoidable (annotate with `// eslint-disable-next-line`).
- Use `pnpm` as the package manager.
- Next.js App Router conventions: server components by default, `"use client"` only when needed.
- Use `zod` for runtime validation of API responses.
- Use `React.Suspense` with loading states for async data.
- Use `fetch` with typed wrappers for API communication — no Axios.
- Component files: PascalCase (e.g., `ChatWindow.tsx`). Hooks: camelCase with `use` prefix.
- Prefer named exports over default exports.
- CSS: Tailwind utility classes. Extract repeated patterns to component variants via `cva` (class-variance-authority).
- State management: React context + `useReducer` for complex state, or Zustand if global state grows.

```typescript
// Good
interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  toolCalls?: ToolCall[];
  timestamp: Date;
}

export function MessageBubble({ message }: { message: ChatMessage }) {
  // ...
}
```

---

## Agent Architecture (LangGraph)

### Orchestrator Pattern

Use a **supervisor/router** pattern in LangGraph. The orchestrator receives user input, classifies intent, and delegates to the appropriate specialist agent.

```
User Input → Orchestrator → [Chat | SQL | Document | RAG | Web] Agent → Response
                ↑                                                          │
                └──────────────── (may route to another agent) ←───────────┘
```

### Agent Design Rules

1. **Single Responsibility**: Each agent handles one domain (SQL, documents, RAG, etc.).
2. **Shared State**: Use a typed `AgentState` (TypedDict) passed through the LangGraph graph. Never use global mutable state.
3. **Tool Binding**: Bind tools to agents via `llm.bind_tools()`. Each agent gets only the tools relevant to its domain.
4. **Graceful Degradation**: If a tool call fails, the agent must report the failure meaningfully — never silently swallow errors.
5. **Token Budget**: Always set `max_tokens` on LLM calls. For Ollama local models, keep prompts concise to maintain speed.
6. **Streaming**: All agents must support streaming via LangGraph's `astream_events` for real-time UI updates.

### SQL Agent Specific Rules

- **Read-only by default**. Only SELECT queries unless the user explicitly enables write mode in settings.
- **Always validate generated SQL** before execution:
  - Parse with `sqlglot` or `sqlparse` to verify syntax.
  - Check for destructive operations (DROP, DELETE, TRUNCATE, ALTER).
  - Enforce `LIMIT` clause (default 100 rows) to prevent unbounded result sets.
- **Schema introspection**: Always provide the LLM with the target database schema (tables, columns, types, foreign keys) in the system prompt.
- **Query explanation**: After executing, return both the raw results and a natural language explanation.
- **Connection isolation**: Use separate read-only SQLAlchemy sessions for query execution.

```python
# SQL Agent safety pattern
FORBIDDEN_KEYWORDS = {"DROP", "DELETE", "TRUNCATE", "ALTER", "INSERT", "UPDATE", "CREATE", "GRANT", "REVOKE"}

def validate_query(sql: str, allow_writes: bool = False) -> str:
    """Validate and sanitize a SQL query before execution."""
    parsed = sqlparse.parse(sql)
    for statement in parsed:
        stmt_type = statement.get_type()
        if not allow_writes and stmt_type != "SELECT":
            raise UnsafeQueryError(f"Only SELECT queries are allowed. Got: {stmt_type}")
        tokens = {t.ttype: t.value.upper() for t in statement.flatten() if t.ttype is not None}
        # Additional keyword checks...
    if "LIMIT" not in sql.upper():
        sql = f"{sql.rstrip(';')} LIMIT 100;"
    return sql
```

### Document Agent Specific Rules

- Support all formats: PDF, DOCX, XLSX, PPTX, CSV, HTML, Markdown, PNG, JPG, TIFF.
- Use the **Unstructured** library as the primary parser with fallbacks:
  - PDF: `unstructured` → `PyMuPDF` fallback
  - Images: `EasyOCR` or `Surya` for OCR → vision model for complex layouts
  - Office: `python-docx`, `openpyxl`, `python-pptx`
- **Table extraction**: Use `pdfplumber` or `camelot` for precise table extraction from PDFs.
- **Chunking strategy**: Recursive character text splitter with chunk size 1000, overlap 200. Preserve document structure (headings, sections).
- File size limit: Configurable, default 50MB. Validate MIME type server-side — never trust client-provided content types.
- Store parsed content with metadata (source file, page number, section) for citation tracking.

### RAG Pipeline Rules

- **Embedding model**: `nomic-embed-text` via Ollama. Dimension: 768.
- **Vector store**: Qdrant with dense and BM25 vectors.
- **Retrieval**: Use the shared hybrid retrieval service with the selected `rag` or `rag_v2` profile and weighted reciprocal rank fusion. RRF values are ranks, not confidence or cosine scores.
- **Context window management**: Concatenate retrieved chunks but never exceed 70% of the model's context window. Prioritize by relevance score.
- **Citation**: Every RAG response must include source references (document name, page/section).

---

## MCP Server Development

### Building MCP Servers

Use the `FastMCP` high-level API from the `mcp` Python SDK.

```python
from mcp.server.fastmcp import FastMCP

sql_mcp = FastMCP("SQL Tools", description="SQL database query and introspection tools")

@sql_mcp.tool()
async def query_database(sql: str, database: str = "default") -> str:
    """Execute a read-only SQL query against the specified database.

    Args:
        sql: The SQL SELECT query to execute.
        database: The database connection name from configuration.
    """
    validated_sql = validate_query(sql)
    result = await execute_query(validated_sql, database)
    return format_results(result)

@sql_mcp.resource("schema://{database}")
async def get_schema(database: str) -> str:
    """Get the full schema of a database."""
    return await introspect_schema(database)
```

### MCP Server Rules

1. **One server per domain**: SQL server, document server, RAG server — each in its own module.
2. **Use lifespan managers** for resource setup/teardown (DB connections, model loading).
3. **Tools for actions, Resources for data**: Tools perform operations (query, parse). Resources provide read-only data (schema, config).
4. **Input validation**: Validate all tool inputs with Pydantic. Never pass raw user input to system commands or SQL.
5. **Error handling**: Return meaningful error messages via tool results (`isError: true`). Never crash the server.
6. **Transport**: Default to stdio for local tools. Use streamable-http only for networked/shared servers.

### Consuming External MCP Servers

Use `mcp.ClientSession` to discover configured community MCP servers. Treat discovered tools as operator-only: keep them out of authenticated routes and shared-account LangGraph agents because their calls do not carry account ownership. To support account-facing MCP tools, add account-scoped adapters that enforce file, SQL connection, and RAG collection ownership on each call, then bind only the adapters relevant to that agent type.

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def connect_external_mcp(command: str, args: list[str]) -> list[Tool]:
    """Connect to an external MCP server and discover its tools."""
    server_params = StdioServerParameters(command=command, args=args)
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            mcp_tools = await session.list_tools()
            return convert_to_langchain_tools(mcp_tools, session)
```

---

## API Design (FastAPI)

### Route Conventions

- RESTful resource naming: `/api/v1/{resource}`.
- Use `APIRouter` with tags for grouping.
- All endpoints return typed Pydantic response models.
- Streaming endpoints use `StreamingResponse` or WebSocket.
- Health check at `GET /api/v1/health`.

### Error Response Format

```json
{
  "error": {
    "code": "DOCUMENT_PARSE_ERROR",
    "message": "Failed to parse the uploaded PDF: file is encrypted.",
    "details": {
      "file_name": "report.pdf",
      "suggestion": "Please provide an unencrypted PDF file."
    }
  }
}
```

### WebSocket Protocol (Chat Streaming)

```json
// Client → Server
{"type": "message", "content": "What are the top 5 customers?", "attachments": []}

// Server → Client (streaming)
{"type": "token", "content": "Based"}
{"type": "token", "content": " on"}
{"type": "tool_call", "tool": "query_database", "input": {"sql": "SELECT..."}}
{"type": "tool_result", "tool": "query_database", "output": "..."}
{"type": "token", "content": "The top 5 customers are..."}
{"type": "done", "metadata": {"tokens_used": 450, "agents_invoked": ["sql_agent"]}}
```

---

## Security

### Critical Rules

1. **SQL Injection Prevention**: Never concatenate user input into SQL strings. Use parameterized queries via SQLAlchemy. The SQL agent generates queries from natural language — always validate generated SQL before execution.
2. **File Upload Safety**: Validate MIME types server-side (use `python-magic`). Restrict upload size. Never execute uploaded files. Store uploads outside the web root.
3. **Path Traversal**: Sanitize all file paths. Reject paths containing `..` or absolute paths when relative is expected. Use `pathlib.Path.resolve()` and verify the result is within the allowed directory.
4. **No Secrets in Code**: Use `.env` files (never committed) via `pydantic-settings`. Provide `.env.example` with placeholder values.
5. **CORS**: Restrict to `localhost:3000` (frontend) in development. Configurable for production.
6. **Rate Limiting**: Apply rate limits on all endpoints, especially LLM-bound ones, to prevent resource exhaustion.
7. **Input Validation**: Every API endpoint validates input with Pydantic. Reject payloads exceeding size limits.
8. **Dependency Pinning**: Pin all Python dependencies in `uv.lock`. Pin npm dependencies in `pnpm-lock.yaml`. Run `uv audit` / `pnpm audit` in CI.

---

## Error Handling Patterns

### Python Backend

```python
# Define domain-specific exception hierarchy
class AppError(Exception):
    """Base application error."""
    def __init__(self, message: str, code: str, status_code: int = 500):
        self.message = message
        self.code = code
        self.status_code = status_code

class DocumentParseError(AppError):
    def __init__(self, message: str):
        super().__init__(message=message, code="DOCUMENT_PARSE_ERROR", status_code=422)

class UnsafeQueryError(AppError):
    def __init__(self, message: str):
        super().__init__(message=message, code="UNSAFE_QUERY", status_code=400)

class LLMConnectionError(AppError):
    def __init__(self, message: str = "Failed to connect to Ollama"):
        super().__init__(message=message, code="LLM_CONNECTION_ERROR", status_code=503)

# FastAPI exception handler (registered in main.py)
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    logger.error("app_error", code=exc.code, message=exc.message, path=request.url.path)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )
```

### TypeScript Frontend

```typescript
// Typed API error handling
class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public statusCode: number,
  ) {
    super(message);
  }
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(
      body?.error?.code ?? "UNKNOWN_ERROR",
      body?.error?.message ?? res.statusText,
      res.status,
    );
  }

  return res.json() as Promise<T>;
}
```

---

## Testing

### Python

- Use `pytest` with `pytest-asyncio` for async tests.
- **Unit tests** for all tools, services, and utility functions.
- **Integration tests** for API endpoints using `httpx.AsyncClient` with FastAPI's `TestClient`.
- **Agent tests**: Mock the LLM with deterministic responses to test agent routing and tool invocation logic.
- Minimum coverage target: 80% for services and tools, 60% for agents (LLM-dependent logic is harder to test).
- Fixtures in `conftest.py`: test database, mock Ollama client, sample documents.

### TypeScript

- Use `vitest` for unit tests, `Playwright` for E2E tests.
- Test API client functions with mocked `fetch`.
- Test components with React Testing Library.
- E2E: Test critical flows (send chat message, receive streaming response, upload document, view extraction).

### Running Tests

```bash
# Backend
cd backend && uv run pytest -v --cov=app --cov-report=term-missing

# Frontend
cd frontend && pnpm test

# E2E
cd frontend && pnpm test:e2e
```

---

## Performance (Apple Silicon Optimization)

1. **Ollama Metal acceleration**: Ensure Ollama is built with Metal support (default on macOS). Verify with `ollama --version` and check for Metal in logs.
2. **Model quantization**: Use Q4_K_M quantized models for best speed/quality tradeoff on 8-16GB unified memory.
3. **Concurrent requests**: Ollama processes one request at a time by default. Use `OLLAMA_NUM_PARALLEL=2` for moderate concurrency. Do not exceed available memory.
4. **Embedding batch size**: Batch document embeddings (32-64 chunks per call) to reduce Ollama round-trips.
5. **Qdrant**: Keep the server version pinned and preserve recorded embedding identities. Do not silently change or delete indexed collections.
6. **FastAPI workers**: Use `uvicorn` with 1 worker (Ollama is the bottleneck, not the API). Use async everywhere to avoid blocking.
7. **Frontend**: Use React Server Components for initial page loads. Client-side streaming for chat. Debounce search inputs.

---

## Model Recommendations (Ollama)

Agent profile defaults and selectable models are defined in `backend/app/prompts/**/agent.json`.
RAG also uses Laya for decision checks and Nomic for embeddings.

| Agent or workflow | Default model | Other available choice |
|-------------------|---------------|-------------------------|
| Chat | `llama3.1:8b` | `qwen2.5:7b`, `qwen2.5-coder:7b` |
| Document analytics | `qwen2.5:7b` | `llama3.1:8b` |
| Image analysis | `qwen3-vl:4b` | — |
| RAG and RAG v2 | `qwen2.5:7b` | `llama3.1:8b` |
| Software engineer | `qwen2.5-coder:7b` | `qwen2.5:7b` |
| SQL | `llama3.1:8b` | `qwen2.5:7b`, `qwen2.5-coder:7b` |
| Stock research | `qwen2.5:7b` | `llama3.1:8b` |
| Web | `llama3.1:8b` | `qwen2.5:7b` |
| Laya RAG checks | `laya:latest` | Decision model; not an answer model |
| RAG embeddings | `nomic-embed-text` | Embedding model; not an answer model |

Image fraud analysis uses deterministic image processing, and image generation uses ComfyUI.

Pull this model set when setting up a new machine:

```bash
ollama pull laya:latest
ollama pull llama3.1:8b
ollama pull nomic-embed-text
ollama pull qwen2.5:7b
ollama pull qwen3-vl:4b
ollama pull qwen2.5-coder:7b
```

---

## Development Workflow

### Setup

```bash
# 1. Install prerequisites
brew install ollama uv pnpm tesseract

# 2. Start Ollama and pull models
ollama serve &
ollama pull laya:latest && ollama pull llama3.1:8b && ollama pull nomic-embed-text && \
  ollama pull qwen2.5:7b && ollama pull qwen3-vl:4b && \
  ollama pull qwen2.5-coder:7b

# 3. Backend setup
cd backend
uv sync
cp .env.example .env
cd ..
backend/.venv/bin/alembic -c backend/alembic.ini upgrade head
cd backend
uv run uvicorn app.main:app --reload --port 8000

# 4. Frontend setup
cd frontend
pnpm install
cp .env.example .env.local
pnpm dev
```

### Makefile Targets

```makefile
setup:         # Install all dependencies and pull models
dev:           # Start backend + frontend concurrently
test:          # Run all tests
lint:          # Run ruff (Python) + eslint (TS)
format:        # Auto-format all code
migrate:       # Run database migrations
seed:          # Seed demo database with sample data
clean:         # Remove caches, build artifacts, temp files
```

---

## Configuration

All configuration via environment variables, loaded through `pydantic-settings`.

The application SQLite database is `data/app.db` at the repository root. Run
database migrations and other database changes against this root database. Run
Alembic from the repository root, for example:

```bash
backend/.venv/bin/alembic -c backend/alembic.ini upgrade head
```

Running Alembic from `backend/` can target a separate `backend/data/app.db`
instead.

```env
# .env.example

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_CHAT_MODEL=llama3.1:8b
OLLAMA_VISION_MODEL=qwen3-vl:4b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
LAYA_MODEL=laya:latest

# Database (for SQL Agent target)
SQL_DATABASE_URL=sqlite:///./data/demo.db

# Application Database (chat history, metadata)
APP_DATABASE_URL=sqlite:///./data/app.db

# Qdrant
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION_NAME=documents

# Upload
MAX_UPLOAD_SIZE_MB=50
UPLOAD_DIR=./data/uploads

# API
API_PORT=8000
CORS_ORIGINS=http://localhost:3000

# MCP
MCP_SERVERS_CONFIG=./mcp_servers.json
```

---

## Git Conventions

- Branch naming: `feature/`, `fix/`, `refactor/`, `docs/` prefixes.
- Commit messages: Conventional Commits format (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`).
- PR descriptions must include: what changed, why, how to test.
- No commits directly to `main`. Use feature branches + PRs.
