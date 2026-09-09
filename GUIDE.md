# Local AI Application -- Comprehensive Guide

A fully local, free, production-grade AI application that runs entirely on Apple Silicon Macs using open-source models via Ollama. Zero cloud dependencies. Zero API keys. Fully offline-capable.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start](#quick-start)
3. [Manual Setup](#manual-setup)
4. [Configuration](#configuration)
5. [Running the Application](#running-the-application)
6. [Features](#features)
7. [Architecture](#architecture)
8. [Docker Deployment](#docker-deployment)
9. [MCP Integration](#mcp-integration)
10. [Testing](#testing)
11. [Development Workflow](#development-workflow)
12. [Troubleshooting](#troubleshooting)
13. [API Reference](#api-reference)
14. [Desktop meeting workflow](#desktop-meeting-workflow)

---

## Prerequisites

| Tool     | Minimum Version | Install                          |
|----------|-----------------|----------------------------------|
| macOS    | 13+ (Ventura)   | Apple Silicon (M1/M2/M3/M4)     |
| Ollama   | latest          | `brew install ollama`            |
| Python   | 3.12+           | `brew install python@3.13`       |
| Node.js  | 18+             | `brew install node`              |
| uv       | latest          | `brew install uv`                |
| pnpm     | 9+              | `brew install pnpm`              |

> **Python 3.14 is NOT supported** -- ChromaDB is incompatible. Use Python 3.12 or 3.13.

### Ollama Models

The application uses three models:

| Model               | Size   | Purpose                        |
|----------------------|--------|--------------------------------|
| `llama3.1:8b`       | ~4.7GB | General chat & SQL generation  |
| `nomic-embed-text`  | ~274MB | Document embeddings for RAG    |
| `llama3.2-vision:11b` | ~7.9GB | Vision/OCR (optional)        |

Pull them with:

```bash
ollama pull llama3.1:8b
ollama pull nomic-embed-text
ollama pull llama3.2-vision:11b   # optional, for vision features
```

---

## Quick Start

The fastest way to get running:

```bash
# 1. Clone and enter the project
cd LocalAIApplication

# 2. Run the automated setup script
bash scripts/setup.sh

# 3. Start the application
make dev
```

This will:
- Check all prerequisites are installed
- Create `.env` and `frontend/.env.local` config files
- Install Python and Node.js dependencies
- Pull the required Ollama models
- Run database migrations
- Start the backend (port 8000) and frontend (port 3000)

Open **http://localhost:3000** in your browser.

---

## Desktop meeting workflow

Phase 3 supports one supervised, source-checkout workflow on macOS. It is not a packaged
desktop release. From the repository root, use the supported launcher:

```bash
make dev-desktop
```

The launcher runs the database migration, starts the backend on `127.0.0.1:8000`, waits for
health with `meeting_ready=true`, starts the frontend on `127.0.0.1:3000`, waits for HTTP
readiness, and then runs `cargo tauri dev`. Each owned root runs in its own process group;
child death is monitored while Tauri runs. Readiness uses 0.5-second curl connect and
2-second total request limits within a 20-second polling budget (with at most one in-flight
request extending that bound). It refuses to adopt existing
listeners on ports 8000/3000 and stops only its owned groups on exit (TERM, five-second
graceful wait, then KILL escalation). Ollama and unrelated listeners are never touched. It
does not restart a crashed child; correct the diagnostic and rerun the command. See the
detailed [desktop source-checkout runbook](desktop/README.md).

### macOS prerequisites

In addition to the application prerequisites above, the native host requires:

- Apple Silicon and macOS **13.0 or later**.
- The full Xcode application with its license/first-launch setup complete. Xcode Command Line
  Tools alone are not sufficient because the native bridge links the macOS SDK's
  AVFAudio/AVFoundation, CoreAudio, CoreGraphics, CoreMedia, and ScreenCaptureKit frameworks.
- Rust stable and Tauri 2 CLI (`cargo install tauri-cli --version '^2'`).

The one-time dependency setup is:

```bash
cd backend && uv sync
cd ../frontend && pnpm install
cargo install tauri-cli --version '^2'
```

The backend process starts with `backend/` as its working directory. For the desktop
workflow, put the settings in `backend/.env` (or export them) rather than relying on a root
`.env` that is not in the backend process's working directory:

```bash
cp .env.example backend/.env
mkdir -p backend/data/uploads backend/data/chroma
```

For this launcher, relative backend paths such as `./data/app.db`, `./data/uploads`, and
`./data/chroma` resolve under `backend/`.

### Offline local transcription

Meeting transcription uses CPU/int8 `faster-whisper` with English and VAD. Before starting an
offline run, provision the complete local CTranslate2 model directory and set:

```env
ASR_MODEL_DIR=/absolute/path/to/small.en
ASR_MODEL_NAME=small.en
```

`ASR_MODEL_DIR` must be an existing absolute directory whose basename is exactly `small.en`.
The readiness check loads it with `local_files_only=True`; startup/preflight never downloads
model files, and a missing/incomplete model fails readiness instead of falling back to a
download. Provision or copy the artifact outside meeting runtime. `make setup` is not an
offline desktop command because it pulls Ollama models.

### Diagnostics and recovery

The launcher applies migrations before backend startup. Run these from `backend/` to inspect
the migration state:

```bash
uv run alembic upgrade head
uv run alembic current
uv run alembic heads
```

Inspect health as JSON after startup:

```bash
curl -sS http://127.0.0.1:8000/api/v1/health | python3 -m json.tool
```

The endpoint returns HTTP 200 even when dependencies are down. For a meeting,
`meeting_ready` must be `true`; `local_asr` and `app_database` are required. Ollama and
ChromaDB are marked optional for meeting answers. On backend startup, any meeting left
`active` by a previous backend process is marked `failed`; its persisted transcript remains,
but missing audio cannot be recovered. Start a new meeting after a restart.

### Permissions, capture, and privacy

Grant the debug/signed app **Screen Recording** and **Microphone** access in **System Settings
→ Privacy & Security**. If access is denied, use the meeting preflight's request/settings
action, enable the app in the relevant pane, and explicitly recheck before retrying.

System audio is a **display-wide system mix from the render endpoint**, not a Teams-only or
per-process stream; it may contain notifications, music, alerts, and other non-meeting sound.
Phase 3 does not
provide per-process Teams isolation. The microphone is a separate source. Participants and
other affected users must receive the applicable capture disclosure and consent.

Raw PCM is retained only in bounded native/backend memory. It is not sent through Tauri IPC,
persisted in SQL, or written to logs. Final source-labelled transcript segments, meeting
metadata, and detected questions are persisted; answer suggestions are streamed locally and
are not a separate persisted record. `DELETE /api/v1/meetings/{meeting_id}` purges processor
state and deletes that meeting's transcript/questions; it does not delete unrelated uploads
or RAG collections.

```bash
MEETING_ID="replace-with-meeting-id"
curl -X DELETE "http://127.0.0.1:8000/api/v1/meetings/${MEETING_ID}"
```

The native transport permits one active session per meeting, one unacknowledged chunk per
source, 960-frame chunks, and a 192,000-byte payload limit. Its reconnect loop is bounded to
five attempts; stop drains for at most two seconds. The backend queue defaults to 128 items
and 2,000 ms rolling windows. Capture drops and processor backpressure are reported
separately. These limits are protective bounds, not a guarantee of lossless capture.

Ollama and RAG are optional for the meeting workflow. Ollama supplies private answer
suggestions for detected system-source questions; RAG is disabled by default and can be
enabled with `MEETING_ENABLE_RAG=true` when the local Chroma store is available. If either is
unavailable, a visible degraded event is emitted while transcription continues.

### Windows and packaging gates

The macOS workflow does not certify Windows. Windows validation must run on Windows 10 2004
or later and cover WASAPI loopback, CPAL microphone capture, WAVEFORMATEXTENSIBLE devices,
silent WASAPI packets, and microphone privacy denial. Windows system audio is also a
render-endpoint system mix rather than per-process Teams audio.

Packaging remains disabled. A release still needs a production frontend asset strategy, a
managed/supervised FastAPI runtime and canonical meeting WebSocket, an explicit
desktop-to-backend endpoint/lifecycle policy, Windows hardware smoke, signing, installers,
and a packaged backend runtime.

Run the deterministic launcher checks without starting the application:

```bash
make test-desktop-launcher
```

---

## Manual Setup

If you prefer step-by-step control:

### 1. Start Ollama

```bash
ollama serve &
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

### 2. Backend

```bash
cd backend

# Install Python dependencies
uv sync

# Create config from template
cp ../.env.example ../.env

# Create data directories
mkdir -p ../data/uploads ../data/chroma

# Run database migrations
uv run alembic upgrade head

# Seed the demo database (optional -- creates sample data for SQL agent)
uv run python ../scripts/seed_demo_db.py

# Start the backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Frontend

```bash
cd frontend

# Install Node.js dependencies
pnpm install

# Create local env
echo 'NEXT_PUBLIC_API_URL=http://localhost:8000' > .env.local

# Start the frontend
pnpm dev
```

---

## Configuration

All configuration is via environment variables in the `.env` file (backend) and `frontend/.env.local` (frontend). The `.env.example` file documents every option.

### Key Settings

#### Ollama

| Variable               | Default                    | Description                          |
|------------------------|----------------------------|--------------------------------------|
| `OLLAMA_BASE_URL`      | `http://localhost:11434`   | Ollama server address                |
| `OLLAMA_CHAT_MODEL`    | `llama3.1:8b`              | Model for chat and SQL generation    |
| `OLLAMA_VISION_MODEL`  | `llama3.2-vision:11b`      | Model for image understanding        |
| `OLLAMA_EMBEDDING_MODEL` | `nomic-embed-text`       | Model for document embeddings        |
| `OLLAMA_REQUEST_TIMEOUT` | `120`                    | Seconds before LLM request timeout   |
| `OLLAMA_NUM_PARALLEL`  | `2`                        | Concurrent Ollama requests           |

#### Meeting Transcription

| Variable                 | Default / requirement             | Description                                      |
|--------------------------|-----------------------------------|--------------------------------------------------|
| `ASR_MODEL_DIR`          | none; absolute `small.en` folder | Pre-provisioned local CTranslate2 model path    |
| `ASR_MODEL_NAME`         | `small.en`                        | Required offline ASR model name                 |
| `MEETING_AUDIO_QUEUE_SIZE` | `128`                           | Maximum queued processor items                  |
| `MEETING_PCM_WINDOW_MS`  | `2000`                            | Rolling local transcription window in ms        |
| `MEETING_ENABLE_RAG`     | `false`                           | Enable optional local Chroma retrieval          |

#### Databases

| Variable             | Default                                  | Description                              |
|----------------------|------------------------------------------|------------------------------------------|
| `SQL_DATABASE_URL`   | `sqlite+aiosqlite:///./data/demo.db`     | Database the SQL agent queries against   |
| `APP_DATABASE_URL`   | `sqlite+aiosqlite:///./data/app.db`      | Internal DB for chat history & metadata  |

#### RAG (Retrieval-Augmented Generation)

| Variable              | Default | Description                                    |
|-----------------------|---------|------------------------------------------------|
| `CHROMA_PERSIST_DIR`  | `./data/chroma` | ChromaDB persistent storage location   |
| `RAG_CHUNK_SIZE`      | `1000`  | Characters per document chunk                  |
| `RAG_CHUNK_OVERLAP`   | `200`   | Overlap between adjacent chunks                |
| `RAG_TOP_K`           | `5`     | Number of results returned per search          |
| `RAG_SCORE_THRESHOLD` | `0.4`   | Minimum similarity score (0.0-1.0)             |

#### Document Upload

| Variable              | Default | Description                                    |
|-----------------------|---------|------------------------------------------------|
| `MAX_UPLOAD_SIZE_MB`  | `50`    | Maximum file upload size                       |
| `UPLOAD_DIR`          | `./data/uploads` | Where uploaded files are stored       |
| `ALLOWED_EXTENSIONS`  | `.pdf,.docx,...` | Comma-separated list of allowed types  |

#### Rate Limiting

| Variable              | Default       | Description                              |
|-----------------------|---------------|------------------------------------------|
| `RATE_LIMIT_DEFAULT`  | `60/minute`   | Default rate limit for all endpoints     |
| `RATE_LIMIT_LLM`      | `10/minute`   | Rate limit for LLM-bound endpoints       |
| `RATE_LIMIT_UPLOAD`   | `20/minute`   | Rate limit for file upload               |

#### SQL Agent Safety

| Variable           | Default | Description                                     |
|--------------------|---------|-------------------------------------------------|
| `SQL_MAX_ROWS`     | `100`   | Maximum rows returned per query                 |
| `SQL_ALLOW_WRITES` | `false` | Allow INSERT/UPDATE/DELETE (dangerous)          |

#### Frontend

| Variable              | Default                  | Where                 |
|-----------------------|--------------------------|-----------------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000`  | `frontend/.env.local` |
| `NEXT_PUBLIC_WS_URL`  | `ws://localhost:8000`    | `frontend/.env.local` |

---

## Running the Application

### Using Make (recommended)

```bash
# Start both backend and frontend
make dev

# Start only the backend
make dev-backend

# Start only the frontend
make dev-frontend
```

### Backend Only

```bash
cd backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend Only

```bash
cd frontend
pnpm dev
```

### Accessing the Application

| URL                        | Description              |
|----------------------------|--------------------------|
| http://localhost:3000      | Web UI                   |
| http://localhost:8000      | API server               |
| http://localhost:8000/docs | Interactive API docs     |
| http://localhost:11434     | Ollama API               |

---

## Features

### Chat

The main conversational interface with streaming responses. The orchestrator automatically routes queries to the appropriate specialist agent.

- **Streaming**: Real-time token-by-token responses via WebSocket
- **Markdown rendering**: Assistant responses render with full Markdown support (code blocks, tables, lists, links)
- **Tool call visibility**: See which tools the agent invokes and their inputs/outputs
- **Conversation history**: Conversations are persisted to the database and listed in the sidebar
- **Auto-reconnect**: WebSocket automatically reconnects with exponential backoff on disconnection

### SQL Agent

Natural language to SQL -- ask questions about your data in plain English.

- **Natural language queries**: "Show me the top 5 customers by order count"
- **Raw SQL execution**: Write and execute SQL directly with validation
- **Schema browser**: Explore tables, columns, types, and primary keys
- **Database selector**: Switch between multiple registered database connections
- **Safety**: Only SELECT queries allowed by default. Automatic LIMIT enforcement. All generated SQL is validated before execution.

### Document Intelligence

Upload and analyze documents in many formats.

**Supported formats**: PDF, DOCX, XLSX, PPTX, CSV, HTML, Markdown, TXT, PNG, JPG, JPEG, TIFF, BMP

- **Upload**: Drag-and-drop or click to upload files
- **Analysis**: Ask questions about uploaded documents
- **OCR**: Extract text from images using EasyOCR
- **Table extraction**: Extract structured tables from PDFs

### RAG (Retrieval-Augmented Generation)

Embed documents into a vector store and search them semantically.

- **Ingest**: Select uploaded documents and ingest them into named collections
- **Search**: Semantic search across your knowledge base with relevance scores
- **Collections**: Organize documents into collections, view counts, delete collections
- **Citations**: Search results include source document and page references

**Workflow**:
1. Upload documents on the **Documents** page
2. Go to the **RAG** page
3. Select documents and click **Ingest** to add them to a collection
4. Use the search bar to query your knowledge base

### Web Research Agent

Scrape and summarize web content locally without API keys.

- Fetch and extract text from URLs
- Extract links from web pages
- Multi-URL fetch for comparative research

### MCP Integration

Expose application tools as MCP servers and consume external community MCP servers.

See the [MCP Integration](#mcp-integration) section below for details.

---

## Architecture

```
Frontend (Next.js, port 3000)
    |
    | REST + WebSocket
    |
Backend (FastAPI, port 8000)
    |
    +-- LangGraph Orchestrator
    |       |
    |       +-- Chat Agent
    |       +-- SQL Agent     --> SQLAlchemy --> Database
    |       +-- Document Agent --> PyMuPDF / EasyOCR
    |       +-- RAG Agent     --> ChromaDB (vector store)
    |       +-- Web Agent     --> httpx (web fetching)
    |       +-- MCP Tools     --> External MCP servers
    |
    +-- Ollama (port 11434) -- Metal-accelerated on Apple Silicon
```

### Backend Stack

| Component          | Technology                                    |
|--------------------|-----------------------------------------------|
| Web framework      | FastAPI (async, WebSocket support)             |
| Agent framework    | LangGraph + LangChain                         |
| LLM runtime        | Ollama (ChatOllama)                           |
| Embeddings         | Ollama (OllamaEmbeddings, nomic-embed-text)   |
| Vector store       | ChromaDB (persistent, local)                  |
| SQL abstraction    | SQLAlchemy 2.0 (async, aiosqlite)             |
| Document parsing   | PyMuPDF, python-docx, openpyxl, pdfplumber    |
| OCR                | EasyOCR                                       |
| MCP SDK            | FastMCP (mcp Python SDK)                      |
| Rate limiting      | slowapi                                       |
| Validation         | Pydantic v2                                   |
| Logging            | structlog                                     |

### Frontend Stack

| Component          | Technology                                    |
|--------------------|-----------------------------------------------|
| Framework          | Next.js 16 (App Router)                       |
| Language           | TypeScript (strict mode)                      |
| UI components      | shadcn/ui + Radix UI                          |
| Styling            | Tailwind CSS v4                               |
| Markdown           | react-markdown + remark-gfm                   |
| State management   | React hooks + Zustand                         |
| Validation         | Zod v4                                        |
| Testing            | Vitest + React Testing Library                |

### Agent Routing

The LangGraph orchestrator classifies user intent and routes to specialist agents:

| User Intent          | Agent Routed To  | Tools Available                     |
|----------------------|------------------|-------------------------------------|
| General questions    | Chat Agent       | (direct LLM response)              |
| Database questions   | SQL Agent        | sql_query, sql_schema, sql_validate |
| Document analysis    | Document Agent   | document_parse, document_ocr       |
| Knowledge search     | RAG Agent        | rag_search, rag_ingest             |
| Web research         | Web Agent        | web_fetch, web_search_links        |

---

## Docker Deployment

Docker Compose is provided for containerized deployment with three profiles.

### Profiles

| Profile  | Services                            | Use Case                               |
|----------|-------------------------------------|----------------------------------------|
| `infra`  | Ollama + ChromaDB                   | Run infrastructure in containers       |
| `app`    | Backend + Frontend                  | Run application in containers          |
| `full`   | All four services                   | Full containerized deployment          |

### Quick Docker Start

```bash
# Full deployment (all services)
make docker-up

# Infrastructure only (recommended for Apple Silicon -- use native Ollama)
make docker-infra

# Application only (use native Ollama + Docker ChromaDB)
make docker-app

# Stop everything
make docker-down
```

> **Apple Silicon note**: The Docker Ollama container uses CPU-only inference. For Metal GPU acceleration, run Ollama natively (`ollama serve`) and use `docker-infra` for ChromaDB only, or `docker-app` for the application services.

### Docker Configuration

Docker uses `.env.docker` which differs from `.env.example` in:
- `OLLAMA_BASE_URL=http://ollama:11434` (Docker service name)
- `CHROMA_HOST=chromadb` and `CHROMA_PORT=8000` (HttpClient connection)

### Exposed Ports

| Service   | Host Port | Container Port |
|-----------|-----------|----------------|
| Frontend  | 3000      | 3000           |
| Backend   | 8000      | 8000           |
| ChromaDB  | 8100      | 8000           |
| Ollama    | 11434     | 11434          |

---

## MCP Integration

### Built-in MCP Servers

The application exposes three MCP servers that can be consumed by external MCP clients:

| Server            | Module                             | Tools Exposed                         |
|-------------------|------------------------------------|---------------------------------------|
| SQL Server        | `app.mcp.servers.sql_server`       | query_database, get_schema            |
| Document Server   | `app.mcp.servers.document_server`  | parse_document, ocr_document          |
| RAG Server        | `app.mcp.servers.rag_server`       | search_documents, ingest_document     |

Start an MCP server:

```bash
make mcp-sql       # Start SQL MCP server
make mcp-document   # Start Document MCP server
make mcp-rag        # Start RAG MCP server
```

### Consuming External MCP Servers

Configure external MCP servers in `mcp_servers.json` (copy from `mcp_servers.json.example`):

```json
{
    "servers": [
        {
            "name": "weather",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-weather"],
            "transport": "stdio"
        },
        {
            "name": "filesystem",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp/data"],
            "transport": "stdio"
        }
    ]
}
```

External MCP server tools are automatically discovered at application startup and made available to the LangGraph agents.

---

## Testing

### Running Tests

```bash
# All tests
make test

# Backend only (with coverage)
make test-backend
# or directly:
cd backend && uv run pytest -v --cov=app --cov-report=term-missing

# Frontend only
make test-frontend
# or directly:
cd frontend && pnpm test

# E2E tests (Playwright)
make test-e2e
```

### Test Counts

| Suite    | Tests  | Framework                          |
|----------|--------|------------------------------------|
| Backend  | 523    | pytest + pytest-asyncio            |
| Frontend | 264    | vitest + React Testing Library     |
| **Total**| **787**|                                    |

### Coverage Targets (per AGENTS.md)

| Area             | Target |
|------------------|--------|
| Services & tools | 80%    |
| Agents           | 60%    |

### Backend Test Structure

```
backend/tests/
  conftest.py              # Shared fixtures (test DB, mock Ollama, async client)
  test_api/
    test_chat_routes.py    # 56 tests -- REST + WebSocket chat endpoints
    test_document_routes.py # Document upload & analysis endpoints
    test_sql_routes.py     # SQL query, execute, schema, connections
    test_rag_routes.py     # RAG search, ingest, collections
    test_tool_routes.py    # Tool listing endpoint
    test_health.py         # Health check endpoint
  test_agents/
    test_orchestrator.py   # Agent routing and orchestration
    test_chat_agent.py     # Chat agent behavior
    test_sql_agent.py      # SQL agent behavior
  test_services/
    test_llm.py            # LLM service wrapper
    test_embeddings.py     # Embedding service
    test_vector_store.py   # ChromaDB operations
    test_document_parser.py # Document parsing pipeline
    test_ocr.py            # OCR engine
    test_database.py       # Database engine/session management
  test_tools/
    test_sql_tools.py      # SQL validation, execution, schema introspection
    test_document_tools.py # Document parsing tools
    test_rag_tools.py      # RAG search and ingest tools
    test_web_tools.py      # Web fetching tools
    test_filesystem_tools.py # File read/list tools
    test_calculator_tools.py # Calculator tools
  test_mcp/
    test_client.py         # MCP client session management
    test_sql_server.py     # SQL MCP server
    test_document_server.py # Document MCP server
    test_rag_server.py     # RAG MCP server
  test_config.py           # Configuration loading
  test_middleware.py        # Error handling, CORS, rate limiting
```

### Frontend Test Structure

```
frontend/src/
  app/__tests__/
    page.test.tsx          # Dashboard page
    chat.test.tsx          # Chat page
    documents.test.tsx     # Documents page
    sql.test.tsx           # SQL page (11 tests)
    settings.test.tsx      # Settings page
  app/rag/__tests__/
    page.test.tsx          # RAG page (19 tests, including ingest UI)
  components/chat/__tests__/
    ChatWindow.test.tsx    # Chat window component
    MessageBubble.test.tsx # Message display (13 tests)
    StreamingText.test.tsx # Streaming text (5 tests)
    ToolCallDisplay.test.tsx # Tool call display (12 tests)
  components/sql/__tests__/
    QueryEditor.test.tsx   # SQL query editor
    ResultsTable.test.tsx  # Results table (12 tests)
    SchemaBrowser.test.tsx # Schema browser (10 tests)
  components/shared/__tests__/
    Header.test.tsx        # App header (17 tests)
    ThemeProvider.test.tsx  # Theme switching
  hooks/__tests__/
    useChat.test.ts        # Chat hook (12 tests)
    useWebSocket.test.ts   # WebSocket hook (20 tests, including reconnect)
    useMobile.test.ts      # Mobile detection
  lib/__tests__/
    api.test.ts            # API client (27 tests)
    utils.test.ts          # Utility functions
    constants.test.ts      # Constants validation
```

---

## Development Workflow

### Makefile Targets

| Target           | Description                                      |
|------------------|--------------------------------------------------|
| `make setup`     | Full setup (deps, models, migrations, env files) |
| `make dev`       | Start backend + frontend concurrently            |
| `make dev-backend` | Start backend only (port 8000)                 |
| `make dev-frontend` | Start frontend only (port 3000)               |
| `make dev-desktop` | Run the supervised macOS source-checkout workflow |
| `make test-desktop-launcher` | Run deterministic launcher supervision checks |
| `make test`      | Run all tests (backend + frontend)               |
| `make lint`      | Run linters (ruff + eslint)                      |
| `make format`    | Auto-format all code                             |
| `make migrate`   | Run Alembic database migrations                  |
| `make seed`      | Seed demo database with sample data              |
| `make clean`     | Remove caches and build artifacts                |
| `make clean-data`| Remove all runtime data (DB, uploads, vectors)   |

### Code Quality

```bash
# Lint
make lint
# or individually:
cd backend && uv run ruff check .
cd frontend && pnpm lint

# Format
make format
# or individually:
cd backend && uv run ruff format .
cd frontend && pnpm format
```

### Adding a New Database Connection

The SQL agent can query multiple databases. Register additional connections via the API:

```bash
curl -X POST http://localhost:8000/api/v1/sql/connections \
  -H "Content-Type: application/json" \
  -d '{"name": "production", "url": "sqlite:///path/to/production.db"}'
```

Or use the database selector dropdown on the SQL page after registering connections.

### Adding External MCP Servers

1. Copy `mcp_servers.json.example` to `mcp_servers.json`
2. Add your server configuration
3. Restart the backend -- tools are discovered at startup

---

## Troubleshooting

### Ollama Not Running

```
Error: Failed to connect to Ollama
```

**Fix**: Start Ollama with `ollama serve` or check it's running:
```bash
curl http://localhost:11434/api/tags
```

### Model Not Found

```
Error: model "llama3.1:8b" not found
```

**Fix**: Pull the required model:
```bash
ollama pull llama3.1:8b
```

### SQLite "Database is Locked"

This can happen with concurrent access. The application uses WAL mode and busy_timeout to mitigate this. If you still see errors:

**Fix**: Ensure only one backend process is running. Check for stale `.db-wal` and `.db-shm` files in `data/`.

### ChromaDB Connection Failed (Docker)

```
Error: Could not connect to ChromaDB
```

**Fix**: Verify ChromaDB is running and accessible:
```bash
curl http://localhost:8100/api/v1/heartbeat
```

Ensure `.env.docker` has `CHROMA_HOST=chromadb` and `CHROMA_PORT=8000`.

### Frontend WebSocket Not Connecting

If the chat doesn't stream responses:

**Fix**: Verify `NEXT_PUBLIC_WS_URL` in `frontend/.env.local`:
```
NEXT_PUBLIC_WS_URL=ws://localhost:8000
```

If using the Next.js proxy, set it to empty string. For direct backend connection, use `ws://localhost:8000`.

### Python 3.14 Compatibility

ChromaDB does not support Python 3.14. If you see import errors:

**Fix**: Use Python 3.12 or 3.13:
```bash
brew install python@3.13
uv python pin 3.13
uv sync
```

### Port Already in Use

```
Error: Address already in use (port 8000)
```

**Fix**: Kill the existing process:
```bash
lsof -ti:8000 | xargs kill -9
```

### RAG Search Returns No Results

If searches return empty despite having ingested documents:

- Check `RAG_SCORE_THRESHOLD` in `.env` -- the default is `0.4`. Lower it (e.g., `0.2`) for more lenient matching
- Verify documents were ingested: check the collection count on the RAG page
- Try broader search queries

### Rate Limiting (429 Too Many Requests)

The API has rate limits to prevent resource exhaustion:

| Endpoint Type | Default Limit  |
|---------------|----------------|
| General       | 60/minute      |
| LLM-bound     | 10/minute      |
| File upload   | 20/minute      |

Adjust limits in `.env` if needed for development.

---

## API Reference

### Chat

| Method | Endpoint                           | Description                    |
|--------|------------------------------------|--------------------------------|
| POST   | `/api/v1/chat`                     | Send a message (REST)          |
| WS     | `/api/v1/chat/stream`              | Streaming chat (WebSocket)     |
| GET    | `/api/v1/chat/conversations`       | List all conversations         |
| GET    | `/api/v1/chat/conversations/:id`   | Get conversation with messages |
| DELETE | `/api/v1/chat/conversations/:id`   | Delete a conversation          |

#### WebSocket Protocol

```
Client -> Server:
{"type": "message", "content": "What are the top customers?", "attachments": []}

Server -> Client (streaming):
{"type": "token", "content": "Based"}
{"type": "token", "content": " on"}
{"type": "tool_call", "tool": "query_database", "input": {"sql": "SELECT..."}}
{"type": "tool_result", "tool": "query_database", "output": "..."}
{"type": "token", "content": "The top customers are..."}
{"type": "done", "metadata": {"tokens_used": 450, "agents_invoked": ["sql_agent"]}}
```

### Documents

| Method | Endpoint                                 | Description              |
|--------|------------------------------------------|--------------------------|
| POST   | `/api/v1/documents/upload`               | Upload a document        |
| GET    | `/api/v1/documents`                      | List all documents       |
| GET    | `/api/v1/documents/:id`                  | Get document details     |
| POST   | `/api/v1/documents/:id/analyze`          | Analyze a document       |
| DELETE | `/api/v1/documents/:id`                  | Delete a document        |

### SQL

| Method | Endpoint                      | Description                        |
|--------|-------------------------------|------------------------------------|
| POST   | `/api/v1/sql/query`           | Natural language to SQL            |
| POST   | `/api/v1/sql/execute`         | Execute raw SQL (validated)        |
| GET    | `/api/v1/sql/schema`          | Get database schema                |
| POST   | `/api/v1/sql/connections`     | Register a database connection     |
| GET    | `/api/v1/sql/connections`     | List database connections          |

### RAG

| Method | Endpoint                           | Description                    |
|--------|------------------------------------|--------------------------------|
| POST   | `/api/v1/rag/search`               | Semantic search                |
| POST   | `/api/v1/rag/ingest`               | Ingest a document              |
| GET    | `/api/v1/rag/collections`          | List collections               |
| DELETE | `/api/v1/rag/collections/:name`    | Delete a collection            |

### Meetings

| Method | Endpoint                                | Description                              |
|--------|-----------------------------------------|------------------------------------------|
| POST   | `/api/v1/meetings`                      | Create a consented meeting               |
| GET    | `/api/v1/meetings/:id`                  | Get meeting metadata and counts          |
| POST   | `/api/v1/meetings/:id/stop`             | Stop and flush a meeting                 |
| DELETE | `/api/v1/meetings/:id`                  | Delete meeting metadata/transcript       |
| WS     | `/api/v1/meetings/:id/stream`           | Control stream and bounded PCM transport |

### Health & Tools

| Method | Endpoint              | Description                        |
|--------|-----------------------|------------------------------------|
| GET    | `/api/v1/health`      | System health check                |
| GET    | `/api/v1/tools`       | List all available tools           |

---

## Performance Tips

1. **Use native Ollama** on Apple Silicon for Metal GPU acceleration (not Docker).
2. **Use Q4_K_M quantized models** for the best speed/quality tradeoff on 8-16GB unified memory.
3. **Set `OLLAMA_NUM_PARALLEL=2`** for moderate concurrency. Don't exceed available memory.
4. **Batch RAG ingestion** -- ingest multiple documents before searching for best indexing performance.
5. **Keep prompts concise** -- local models perform best with focused, clear queries.
6. **Monitor memory** -- `llama3.1:8b` uses ~5GB, `llama3.2-vision:11b` uses ~8GB. Running both simultaneously requires 16GB+ unified memory.

---

## Project Structure

```
LocalAIApplication/
  AGENTS.md               # Technical specification
  GUIDE.md                # This file
  Makefile                # Task runner
  docker-compose.yml      # Docker deployment
  .env.example            # Configuration template
  .env.docker             # Docker-specific config
  mcp_servers.json.example # MCP server config template
  scripts/
    setup.sh              # Automated setup
    run-desktop-local.sh  # Supervised macOS desktop source-checkout launcher
    seed_demo_db.py       # Demo database seeder
  backend/
    pyproject.toml        # Python dependencies
    app/
      main.py             # FastAPI application
      config.py           # Settings (pydantic-settings)
      api/routes/          # REST + WebSocket endpoints
      agents/              # LangGraph agent definitions
      tools/               # Tool implementations
      services/            # Business logic (LLM, DB, vectors)
      mcp/                 # MCP servers + client
      models/              # Pydantic schemas + ORM models
    tests/                 # 523 backend tests
  frontend/
    package.json          # Node.js dependencies
    src/
      app/                # Next.js pages (App Router)
      components/          # React components
      hooks/               # Custom React hooks
      lib/                 # API client, utilities
      types/               # TypeScript type definitions
    (264 frontend tests colocated with source)
  data/                   # Runtime data (gitignored)
    app.db                # Chat history database
    demo.db               # SQL agent target database
    uploads/              # Uploaded documents
    chroma/               # Vector store
```
