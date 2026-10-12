# Local AI Application

A local AI workspace with a chat UI, FastAPI backend, Ollama models, document parsing, hybrid RAG, and specialist agents. The Docker Compose stack includes the app, Ollama, Qdrant, and ChromaDB (for migration workflows).

For the detailed Apple Silicon and native development guide, see [GUIDE.md](GUIDE.md).

## Quick start with Docker

Prerequisites: Docker Desktop (or Docker Engine with Compose) and enough disk and memory for the models you choose. The containerized Ollama service uses CPU inference; native Ollama on Apple Silicon can use Metal.

```bash
test -f .env.docker || cp .env.example .env.docker
```

Edit `.env.docker` and set the Ollama URL for Compose service discovery:

```dotenv
OLLAMA_BASE_URL=http://ollama:11434
```

Start the full stack:

```bash
docker compose --profile full up -d --build
```

Pull models for the examples below. Pull only the models you plan to use:

```bash
docker compose exec ollama ollama pull llama3.1:8b
docker compose exec ollama ollama pull llama3.2:3b
docker compose exec ollama ollama pull gemma3:4b
docker compose exec ollama ollama pull qwen2.5-coder:7b
docker compose exec ollama ollama pull nomic-embed-text
```

Open the app at <http://localhost:3000>. The API is at <http://localhost:8000>; interactive API docs are at <http://localhost:8000/docs>.

Useful Docker commands:

```bash
docker compose --profile full ps       # Check services
docker compose --profile full logs -f   # Follow logs
docker compose --profile full down     # Stop containers; keep named volumes
```

## Available agents

Use `GET /api/v1/agents` to see enabled profiles and whether their approved Ollama models are installed. Profiles with the same target can still have different prompts and retrieval settings.

| Profile (`agent_name`) | Target | Purpose |
|---|---|---|
| `chat` | `chat` | General local conversation and coding help |
| `document_analytics` | `document` | Extract grounded facts, dates, amounts, tables, and action items |
| `image_analysis` | `image_analysis` | Describe an uploaded image using a vision model |
| `image_fraud` | `image_fraud` | Check image metadata and recompression signals; triage only |
| `image_generation` | `image_generation` | Submit a ComfyUI API-format workflow |
| `rag` | `rag` | Answer from retrieved passages with citations |
| `rag_v2` | `rag` | Hybrid retrieval with query rewrites and stricter passage-grounded citations |
| `software_engineer` | `software_engineer` | Read-only review of a mounted workspace |
| `sql` | `sql` | Generate and explain safe database queries |
| `stock_research` | `stock_research` | Combine Finnhub market data with optional supplied context |
| `web` | `web` | Fetch and summarize user-provided web sources |

The general `/api/v1/chat` endpoint can select the `chat`, `sql`, or `web` profile using `agent_name`. Use `/api/v1/tasks` for the other specialist profiles. The task `target` defaults to `auto` and is resolved from the selected profile; when supplied, it must match the profile's target. Model overrides go in `inference.model` and must be allowed for that profile.

## Agent examples

Set a base URL and define small helpers for the requests below:

```bash
API=http://localhost:8000/api/v1

chat() {
  curl -sS "$API/chat" -H 'Content-Type: application/json' -d "$1"
}

task() {
  curl -sS "$API/tasks" -H 'Content-Type: application/json' -d "$1"
}
```

Upload a file for image examples and copy the response's `id` into the
`asset_id` field:

```bash
curl -sS -F 'file=@./photo.png' "$API/documents/upload"
```

### Chat

```bash
chat '{"agent_name":"chat","content":"Explain hybrid retrieval in simple terms."}'
```

### Document analytics

Supply text directly with `context`, or upload a file using the command above and pass its `asset_id`.

```bash
task '{"agent_name":"document_analytics","prompt":"Extract the invoice total and due date.","context":"Invoice 1042. Total: $84.25. Due: November 15, 2026.","inference":{"model":"llama3.2:3b"}}'
```

### Image analysis

```bash
task '{"agent_name":"image_analysis","prompt":"Describe the main objects and colors.","asset_id":"<DOCUMENT_ID>","inference":{"model":"gemma3:4b"}}'
```

### Image fraud screening

```bash
task '{"agent_name":"image_fraud","prompt":"Screen this image for basic manipulation signals.","asset_id":"<DOCUMENT_ID>"}'
```

The result is a triage signal, not proof that an image is authentic or fraudulent.

### Image generation

Replace the workflow value with a workflow exported in ComfyUI API format. ComfyUI must be running; set `COMFYUI_URL` in your shell or the Compose root `.env` file so the backend container can reach it.

```bash
task '{"agent_name":"image_generation","prompt":"Generate an image.","workflow":{"<node-id>":{"class_type":"<ComfyUI node>","inputs":{}}}}'
```

### RAG and RAG v2

Upload and ingest a document once before asking questions. Use the same collection name in the ingest and task requests.

```bash
curl -sS -F 'file=@./manual.pdf' "$API/documents/upload"
# Copy the returned id into DOCUMENT_ID.
DOCUMENT_ID="<returned-id>"

curl -sS "$API/rag/ingest" -H 'Content-Type: application/json' \
  -d "{\"document_id\":\"$DOCUMENT_ID\",\"collection\":\"manuals\"}"

task '{"agent_name":"rag","prompt":"What is the warranty period?","collection":"manuals","inference":{"model":"llama3.2:3b"}}'
task '{"agent_name":"rag_v2","prompt":"What is the warranty period?","collection":"manuals","inference":{"model":"llama3.2:3b"}}'
```

`rag` uses hybrid dense and BM25 retrieval. `rag_v2` also uses query rewrites. Both return citations when relevant passages are found.

### Software engineer

With Docker, the host `./workspace` directory is mounted read-only. Put a project in that directory and pass its relative path. To mount a different host folder, set `AGENT_WORKSPACE_HOST_PATH` in your shell or the Compose root `.env` file before starting the stack.

```bash
task '{"agent_name":"software_engineer","prompt":"Review the code for correctness and explain the highest-priority issue.","workspace_path":"my-project","inference":{"model":"qwen2.5-coder:7b"}}'
```

The agent reads a bounded sample of supported text files; it does not edit files or run commands.

### SQL

The SQL profile selected through `/chat` uses the default database configured by `SQL_DATABASE_URL`; set that in `.env.docker`. For a named connection, register it with `POST /api/v1/sql/connections` and query it through `/api/v1/sql/query`.

```bash
chat '{"agent_name":"sql","content":"List the five customers with the highest revenue."}'
```

For a direct natural-language query against a selected registered database, use `POST /api/v1/sql/query`:

```bash
curl -sS "$API/sql/query" -H 'Content-Type: application/json' \
  -d '{"question":"List the five customers with the highest revenue.","database":"default"}'
```

### Stock research

Set `FINNHUB_API_KEY` in `.env.docker` to enable live market data.

```bash
task '{"agent_name":"stock_research","symbol":"AAPL","prompt":"Summarize recent performance and key risks.","inference":{"model":"llama3.2:3b"}}'
```

### Web research

```bash
chat '{"agent_name":"web","content":"Fetch and summarize https://example.com."}'
```

## API endpoints

All REST endpoints use the `/api/v1` prefix. Use `/docs` or `/openapi.json` for the generated schemas and response models.

| Area | Endpoints |
|---|---|
| Health and agents | `GET /health`, `GET /health/ready`, `GET /agents` |
| Chat | `POST /chat`, `WS /chat/stream`, `GET /chat/conversations`, `GET /chat/conversations/{id}`, `DELETE /chat/conversations/{id}` |
| Specialist tasks | `POST /tasks` |
| Documents | `POST /documents/upload`, `GET /documents`, `GET /documents/{id}`, `POST /documents/{id}/analyze`, `DELETE /documents/{id}` |
| RAG | `POST /rag/ingest`, `POST /rag/search`, `GET /rag/collections`, `DELETE /rag/collections/{name}` |
| SQL | `POST /sql/query`, `POST /sql/execute`, `GET /sql/schema`, `POST /sql/connections`, `GET /sql/connections` |
| Tools | `GET /tools`, `POST /tools/execute` |
| Meetings | `POST /meetings`, `GET /meetings/{id}`, `POST /meetings/{id}/stop`, `DELETE /meetings/{id}`, `WS /meetings/{id}/stream` |

## Configuration and local development

- `.env.example` lists supported backend settings. Docker Compose reads `.env.docker` for the backend. Compose interpolation values such as `COMFYUI_URL` and `AGENT_WORKSPACE_HOST_PATH` come from your shell or the root `.env` file.
- Stock research needs `FINNHUB_API_KEY`; image generation needs a reachable ComfyUI server. Other Ollama models are listed by `GET /api/v1/agents`.
- For native development, Apple Silicon setup, and meeting transcription requirements, follow [GUIDE.md](GUIDE.md).
- Backend tests: `cd backend && uv run pytest`
- Frontend tests: `cd frontend && pnpm test`
- Full checks: `make test`; lint with `make lint`
