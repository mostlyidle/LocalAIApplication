# Local AI Application — Beginner Guide

This guide gets a beginner from a clean Apple Silicon Mac to a working local
development checkout. The application has a Next.js web UI, a FastAPI backend,
optional local Ollama and Qdrant RAG services, and a supervised Tauri desktop meeting
workflow.

> **Current status:** the meeting workflow is a **macOS source-checkout workflow**,
> not an installed desktop application. Packaging is disabled. The instructions
> below do not claim Windows support or a distributable release.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Clone and first-time setup](#clone-and-first-time-setup)
3. [Configure the environment](#configure-the-environment)
4. [Run the web application](#run-the-web-application)
5. [Run the macOS desktop meeting workflow](#run-the-macos-desktop-meeting-workflow)
6. [Verify readiness](#verify-readiness)
7. [Features](#features)
8. [Architecture](#architecture)
9. [Docker Deployment](#docker-deployment)
10. [MCP Integration](#mcp-integration)
11. [Testing](#testing)
12. [Development Workflow](#development-workflow)
13. [Troubleshooting](#troubleshooting)
14. [API Reference](#api-reference)

---

## Prerequisites

The supported native workflow requires an **Apple Silicon Mac (M1/M2/M3/M4)
running macOS 13.0 or later**. Install the following software before cloning:

| Software | Why it is needed | Install/check |
|---|---|---|
| Git | Clone the checkout | Usually included with Xcode; check with `git --version` |
| Homebrew | Install the command-line prerequisites | [brew.sh](https://brew.sh) |
| Full Xcode app | Build the native Tauri host and link macOS frameworks | Install from the Mac App Store; Command Line Tools alone are not enough |
| Python 3.12 or 3.13 | Run the backend | `brew install python@3.13` |
| uv | Install and run Python dependencies | `brew install uv` |
| Node.js 20.9+ | Run Next.js 16 | `brew install node` |
| pnpm | Install and run frontend dependencies | `brew install pnpm` |
| Rust stable and Cargo | Build the Tauri host | `brew install rust` |
| Ollama | Optional chat, SQL, answer suggestions, and RAG | `brew install ollama` |

The backend declares Python `>=3.12`. Use Python 3.12 or 3.13; **Python 3.14 is
not supported by the current ChromaDB migration dependency**. Next.js 16 requires Node.js
20.9 or later.

Install the Homebrew prerequisites in one command (after installing Homebrew):

```bash
brew install python@3.13 uv node pnpm rust ollama
```

Check the tools that the scripts use:

```bash
python3 --version   # 3.12 or 3.13
uv --version
node --version
pnpm --version
rustc --version
cargo --version
ollama --version
```

### Select the full Xcode developer directory

After installing Xcode, open it once and complete its first-launch prompts.
Then select the **full** Xcode SDK (not `/Library/Developer/CommandLineTools`):

```bash
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -license accept
sudo xcodebuild -runFirstLaunch
xcode-select -p
xcodebuild -version
```

`xcode-select -p` must print
`/Applications/Xcode.app/Contents/Developer` (or the path to your full Xcode
installation). If Xcode is installed somewhere else, substitute that path in
the `--switch` command. The native bridge uses AVFAudio, AVFoundation,
CoreAudio, CoreGraphics, CoreMedia, and ScreenCaptureKit, so the full app is
required.

## Clone and first-time setup

Clone the repository and enter its root:

```bash
git clone https://github.com/LipDevs/LocalAIApplication.git
cd LocalAIApplication
uv python install 3.13
uv python pin 3.13
```

For the regular web application, the repository's setup script installs the
locked backend/frontend dependencies, creates starter environment files,
creates root-level data directories, pulls the configured Ollama models, and
runs migrations:

```bash
bash scripts/setup.sh
```

The script requires `ollama`, `uv`, `pnpm`, and `node`. If Ollama is not
running, it starts `ollama serve` itself and then pulls `llama3.1:8b`,
`nomic-embed-text`, and `qwen3-vl:4b`. Model pulls can take a long time.
It does **not** provision the meeting ASR model.

The setup script writes `.env` at the repository root, but the Makefile starts
the backend with `backend/` as its working directory and the backend reads
`.env` from its current directory. Before running either web or desktop mode,
make the backend configuration explicit:

```bash
test -f backend/.env || cp .env.example backend/.env
mkdir -p backend/data/uploads backend/data/chroma backend/data/fastembed
```

If you already have a `backend/.env`, do not overwrite your custom settings;
edit it instead. The runtime paths in `.env.example` (`./data/...`) therefore
resolve under `backend/` for the Makefile and desktop launcher.

## Configure the environment

The backend configuration belongs in `backend/.env` for all commands in this
guide. Start from the checked-in template:

```bash
cp .env.example backend/.env
```

At minimum, review these values:

```dotenv
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_CHAT_MODEL=llama3.1:8b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
ASR_MODEL_DIR=/absolute/path/to/small.en
ASR_MODEL_NAME=small.en
MEETING_ENABLE_RAG=false
```

`backend/.env` is ignored by Git. Never put API keys or other secrets in
`GUIDE.md` or commit a personal `.env` file. The complete list of supported
settings is in [.env.example](.env.example). In particular, relative database,
upload, and Chroma paths are relative to `backend/` when using `make dev` or
`make dev-desktop`.

### Required meeting ASR model (provision before the meeting)

Meeting transcription is local CPU/int8 `faster-whisper`. It requires a
**complete, already-provisioned CTranslate2 model directory whose basename is
exactly `small.en`**. This is separate from Ollama and is not an Ollama model.
The repository does not include this model artifact.

Obtain or copy the model artifact before meeting time, outside the application
runtime. For example, if the artifact is already available at
`/path/to/provisioned/small.en`:

```bash
mkdir -p "$HOME/Library/Application Support/LocalAIApplication/models"
cp -R "/path/to/provisioned/small.en" \
  "$HOME/Library/Application Support/LocalAIApplication/models/"
```

Set the resulting **absolute** path in `backend/.env` (quote paths containing
spaces if exporting them in a shell):

```dotenv
ASR_MODEL_DIR=/absolute/path/to/small.en
ASR_MODEL_NAME=small.en
```

The runtime rejects a missing path, a relative path, a parent directory, or a
directory not named `small.en`. It loads with `local_files_only=True` and never
downloads ASR files during startup, preflight, or a meeting. A missing or
incomplete model makes meeting readiness fail; it does not fall back to a
download. `make setup` and `bash scripts/setup.sh` pull Ollama models only and
do not provision this ASR artifact.

Check the path before starting anything:

```bash
ASR_MODEL_DIR="/absolute/path/to/small.en"
test -d "$ASR_MODEL_DIR" && test "$(basename "$ASR_MODEL_DIR")" = "small.en" \
  && printf 'ASR directory found: %s\n' "$ASR_MODEL_DIR"
```

### Optional Ollama models

Ollama is **not required for native meeting capture or transcription**. It is
used for local chat/SQL generation, private answer suggestions, and document
embeddings when RAG is enabled. Start it in a separate terminal when you want
those features:

```bash
ollama serve
```

In another terminal, pull only what you need:

```bash
ollama pull laya:latest          # optional local RAG decision checks
ollama pull llama3.1:8b          # chat, SQL, web, and meeting answer suggestions
ollama pull qwen2.5:7b           # documents, RAG, and stock research
ollama pull qwen3-vl:4b  # image analysis
ollama pull qwen2.5-coder:7b     # software engineer agent
ollama pull nomic-embed-text     # document embeddings for RAG
```

RAG uses Qdrant for dense and BM25 retrieval. Start Qdrant before ingesting or
searching documents (Docker Desktop must be running):

```bash
docker compose up -d qdrant
```

The default native endpoint is `http://localhost:6333`. Document vectors use
the configured Ollama embedding model; FastEmbed's BM25 model downloads to
`FASTEMBED_CACHE_PATH` on first use. `rag_v2` adds query rewrites. RRF scores
are ranking values, not cosine similarity or confidence percentages.

Use the matching names in `OLLAMA_CHAT_MODEL`, `OLLAMA_EMBEDDING_MODEL`, and
`OLLAMA_VISION_MODEL`. To use RAG in meetings, set
`MEETING_ENABLE_RAG=true`; leave it `false` for the default capture-only path.
If Ollama or RAG is unavailable, transcription can continue and the application
reports a visible degraded state.

## Run the web application

This is the simplest browser workflow. From the repository root, use separate
terminals so it is obvious which process is doing what:

**Terminal 1 — optional Ollama server** (needed for chat, SQL, answer
suggestions, or RAG):

```bash
ollama serve
```

**Terminal 2 — FastAPI backend** (API, WebSockets, database access, local ASR):

```bash
make dev-backend
```

**Terminal 3 — Next.js frontend** (browser UI on port 3000):

```bash
make dev-frontend
```

Open <http://localhost:3000>. The backend API and interactive docs are at
<http://localhost:8000> and <http://localhost:8000/docs>. `make dev` is an
equivalent convenience command that starts backend and frontend concurrently,
but it does not start Ollama and its combined output is less beginner-friendly.

Stop each foreground process with `Ctrl-C`. Do not run the separate backend or
frontend commands at the same time as `make dev-desktop`; the desktop launcher
must own those ports.

## Run the macOS desktop meeting workflow

This workflow is for a **source checkout only**. Complete the full Xcode setup,
ASR provisioning, and one-time dependencies first:

```bash
test -f backend/.env || cp .env.example backend/.env
mkdir -p backend/data/uploads backend/data/chroma
cd backend && uv sync
cd ../frontend && pnpm install
cd ../
cargo install tauri-cli --version '^2'
```

Edit `backend/.env` and replace the ASR placeholder with the absolute path to
the complete `small.en` CTranslate2 directory. Then run exactly this command
from the repository root:

```bash
make dev-desktop
```

The launcher runs migrations, starts the backend on `127.0.0.1:8000`, waits for
`/api/v1/health/ready` with `meeting_ready=true`, starts the frontend on
`127.0.0.1:3000`, and starts `cargo tauri dev`. The one foreground terminal
shows logs from the supervised backend/frontend/Tauri session. Leave it open
while using the desktop window; press `Ctrl-C` to stop the session. The launcher
does not start, stop, or adopt Ollama. If Ollama is needed, keep `ollama serve`
running in Terminal 1 and run `make dev-desktop` in Terminal 2.

Do not manually start backend/frontend for this workflow. Ports 8000 and 3000
must be free: the launcher refuses to adopt an existing listener. It also does
not restart a child that crashes; read the diagnostic, correct the problem, and
run `make dev-desktop` again.

### macOS capture permissions and disclosure

Grant the debug/signed **Local AI Application** app both **Screen Recording**
and **Microphone** access in **System Settings → Privacy & Security**. If a
permission request is denied, open the relevant settings pane, enable the app,
and explicitly recheck permissions in the meeting preflight before retrying.

Screen Recording supplies a display-wide system-audio mix, not Teams-only or
per-process audio; notifications, alerts, music, and other sound may be
included. The microphone is a separate source. Tell participants and other
affected users what will be captured and obtain any required consent.

## Verify readiness

After the backend is running, check the required meeting gate:

```bash
curl -sS http://127.0.0.1:8000/api/v1/health/ready | python3 -m json.tool
```

Proceed with a meeting only when `meeting_ready` is `true` and both
`services[].name == "local_asr"` and `services[].name == "app_database"` are
healthy. HTTP 200 alone is not enough. For a complete status view, including
optional Ollama and Chroma checks, use:

```bash
curl -sS http://127.0.0.1:8000/api/v1/health | python3 -m json.tool
```

The desktop launcher's readiness request has bounded timeouts and a 20-second
polling budget. `local_asr` errors usually identify a missing, incomplete, or
incorrectly named model directory. `ollama` and `chromadb` may be unhealthy in
the full health response without preventing capture.

---

## Desktop meeting workflow: implementation details

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
test -f backend/.env || cp .env.example backend/.env
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
Qdrant is marked optional for meeting answers. On backend startup, any meeting left
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

### Manual macOS validation scope

The manual macOS check is a source-checkout check, not a release certification. On an Apple
Silicon Mac with the full Xcode SDK selected, run:

```bash
cd desktop/src-tauri
cargo fmt --check
cargo check
cargo test
cargo build
cargo tauri info
cd ../..
make test-desktop-launcher
```

For an end-to-end manual check, run `make dev-desktop`, grant Microphone and Screen Recording,
confirm both native sources in meeting preflight, and verify that
`/api/v1/health/ready` reports `meeting_ready=true` with the pre-provisioned `small.en` model.
This macOS check covers the supervised launcher and macOS native build/capture path only; it
does not validate Windows audio or packaging.

Ollama and RAG are optional for the meeting workflow. Ollama supplies private answer
suggestions for detected system-source questions; RAG is disabled by default and can be
enabled with `MEETING_ENABLE_RAG=true` when local Qdrant is available. If either is
unavailable, a visible degraded event is emitted while transcription continues.

### Windows limitation

The macOS workflow does not certify Windows. Windows validation must run on Windows 10 2004
or later and cover WASAPI loopback, CPAL microphone capture, WAVEFORMATEXTENSIBLE devices,
silent WASAPI packets, and microphone privacy denial. Windows system audio is also a
render-endpoint system mix rather than per-process Teams audio.

### Packaging limitation

Packaging remains disabled (`bundle.active=false`). A release still needs a production frontend asset strategy, a
managed/supervised FastAPI runtime and canonical meeting WebSocket, an explicit
desktop-to-backend endpoint/lifecycle policy, Windows hardware smoke, signing, installers,
and a packaged backend runtime.

Run the deterministic launcher checks without starting the application:

```bash
make test-desktop-launcher
```

---

## Manual web setup (alternative to the setup script)

If you prefer step-by-step control, run these commands from the repository root.
Use a separate terminal for each foreground process. Use the desktop workflow
above instead when you need native meeting capture:

### 1. Optional: start Ollama

```bash
ollama serve
```

In another terminal, pull the models you want:

```bash
ollama pull llama3.1:8b
ollama pull qwen2.5:7b
ollama pull qwen3-vl:4b
ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text
ollama pull laya:latest
```

### 2. Backend

```bash
mkdir -p backend/data/uploads backend/data/chroma
test -f backend/.env || cp .env.example backend/.env

cd backend
uv sync
uv run alembic upgrade head
uv run python ../scripts/seed_demo_db.py
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The seed command is optional; it creates sample data for the SQL agent in
`backend/data/demo.db`.

### 3. Frontend

```bash
cd frontend
pnpm install
printf 'NEXT_PUBLIC_API_URL=http://localhost:8000\nNEXT_PUBLIC_WS_URL=ws://localhost:8000\n' > .env.local
pnpm dev
```

Run the backend and frontend blocks in separate terminals if you want both
processes in the foreground. The Ollama block is a third terminal; it is not
needed for the backend to start, but it is needed for LLM-backed features.

---

## Configuration

All backend configuration is via `backend/.env` for the commands in this guide;
frontend browser endpoints are in `frontend/.env.local`. The checked-in
`.env.example` documents every backend option.

### Key Settings

#### Ollama

| Variable               | Default                    | Description                          |
|------------------------|----------------------------|--------------------------------------|
| `OLLAMA_BASE_URL`      | `http://localhost:11434`   | Ollama server address                |
| `OLLAMA_CHAT_MODEL`    | `llama3.1:8b`              | Model for chat and SQL generation    |
| `OLLAMA_VISION_MODEL`  | `qwen3-vl:4b`              | Model for image understanding        |
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
| `MEETING_ENABLE_RAG`     | `false`                           | Enable optional local Qdrant hybrid retrieval   |

#### Databases

| Variable             | Default                                  | Description                              |
|----------------------|------------------------------------------|------------------------------------------|
| `SQL_DATABASE_URL`   | `sqlite+aiosqlite:///./data/demo.db`     | Database the SQL agent queries against   |
| `APP_DATABASE_URL`   | `sqlite+aiosqlite:///./data/app.db`      | Internal DB for chat history & metadata  |

#### RAG (Retrieval-Augmented Generation)

| Variable              | Default | Description                                    |
|-----------------------|---------|------------------------------------------------|
| `CHROMA_PERSIST_DIR`  | `./data/chroma` | Legacy Chroma source for explicit migrations |
| `QDRANT_URL`          | `http://localhost:6333` | Qdrant endpoint for hybrid retrieval |
| `FASTEMBED_CACHE_PATH` | `./data/fastembed` | Local BM25/query model cache directory |
| `RAG_BM25_LANGUAGE`   | `english` | BM25 language used for new collections |
| `RAG_CHUNK_SIZE`      | `1000`  | Characters per document chunk                  |
| `RAG_CHUNK_OVERLAP`   | `200`   | Overlap between adjacent chunks                |
| `RAG_TOP_K`           | `5`     | Number of results returned per search          |
| `RAG_SCORE_THRESHOLD` | `0.4`   | Legacy dense-search threshold; hybrid RRF ignores it |

#### Optional Specialist Services

| Variable | Default | Description |
|---|---|---|
| `FINNHUB_API_KEY` | unset | Enables live Finnhub quotes and news for stock research; data access follows your Finnhub plan. |
| `MARKET_DATA_CACHE_SECONDS` | `60` | Per-symbol live-data cache duration. |
| `COMFYUI_URL` | `http://localhost:8188` | Local ComfyUI API for exported workflow submissions. |
| `AGENT_WORKSPACE_ROOT` | `./workspace` | Root for bounded, read-only software-engineer review. |
| `AGENT_WORKSPACE_HOST_PATH` | `./workspace` (Docker) | Host project directory mounted read-only into the backend. |
| `GRAFANA_ADMIN_PASSWORD` | local placeholder | Set a private value before using optional monitoring. |

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

- **Agent profiles**: Choose Auto or a catalogued agent; specialist controls appear for RAG collection, ticker, workspace path, model settings, or ComfyUI workflow.
- **Execution details**: Assistant messages retain citations, artifacts, and limitations in history.
- **Streaming**: Generative profiles send incremental tokens and graph tool events via WebSocket. Deterministic tasks, such as image screening and workflow submission, emit one completed result.
- **Model availability**: The selector labels installed and missing models separately from profile enablement and prefers an installed alternative. If Ollama is unreachable, availability is marked unknown. Reload after installing models.
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

### Specialist Agents

The chat profile selector also exposes vision analysis, image-fraud triage, stock
research, read-only software review, document analytics, and image generation.
Vision and document tasks use uploaded asset IDs resolved by the backend. Stock
research requires an optional Finnhub key; its quote/news data is external. The
software reviewer reads a bounded set of text files under `AGENT_WORKSPACE_ROOT`
and does not modify files or run commands. Image-fraud output is triage only.
Image generation submits a user-provided ComfyUI API workflow and returns its job ID.

### Document Intelligence

Upload and analyze documents in many formats.

**Supported formats**: PDF, DOCX, XLSX, PPTX, CSV, HTML, Markdown, TXT, PNG, JPG, JPEG, TIFF, BMP

- **Upload**: Drag-and-drop or click to upload files
- **Analysis**: Ask questions about uploaded documents
- **OCR**: Extract text from images using EasyOCR
- **Table extraction**: Extract structured tables from PDFs

### RAG (Retrieval-Augmented Generation)

Embed documents in Qdrant and search them with dense and BM25 retrieval fused
using weighted reciprocal-rank fusion. The RAG page offers the standard `rag`
profile and `rag_v2` with query rewrites. Displayed RRF scores are rankings,
not similarity percentages.

- **Ingest**: Select uploaded documents and ingest them into named collections
- **Search**: Semantic search across your knowledge base with relevance scores
- **Collections**: Organize documents into collections, view counts, delete collections
- **Citations**: Search results include source document and page references

Automatic and explicit RAG retrieve evidence before generating an answer and retain
structured citations in conversation history. RAG reserves output space and caps
the prompt budget at 70% of the selected context window. Only complete passages that
fit are included and cited; omitted passages/history are reported as limitations.
Increase the context window if no complete passage fits.

Older AITechStack API collections can be queried under their recorded model/revision
contract without changing their metadata. Because they lack historical weight
digests, responses identify this limitation. Ingestion remains guarded: re-embed
into a new collection to establish a verified embedding identity before new writes.

**Workflow**:
1. Upload documents on the **Documents** page
2. Go to the **RAG** page
3. Select documents and click **Ingest** to add them to a collection
4. Use the search bar to query your knowledge base

#### Migrating an existing Chroma collection

The application never migrates collections at startup. Inspect the old index,
then review a dry-run before running a copy:

```bash
cd backend
uv run python -m app.rag_migrate inventory --source-path ./data/chroma
uv run python -m app.rag_migrate migrate \
  --source-path ./data/chroma \
  --source-collection documents \
  --destination-collection documents
```

Migration is dry-run by default. After reviewing the report and confirming the
source path, collection, Qdrant endpoint, and Ollama model, append `--execute`
to the second command. The source remains intact; failed copies keep their
destination for inspection, so a retry needs a fresh destination collection.

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
    |       +-- RAG Agent     --> Qdrant (dense + BM25 retrieval)
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
| Vector store       | Qdrant (dense + BM25; persistent)             |
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

Docker Compose is provided for containerized deployment with optional infrastructure,
application, full-stack, and observability profiles.

### Profiles

| Profile  | Services                            | Use Case                               |
|----------|-------------------------------------|----------------------------------------|
| `infra`  | Ollama + Qdrant + ChromaDB migration source | Run infrastructure in containers |
| `app`    | Backend + Frontend                  | Run application in containers          |
| `full`   | All application and infrastructure services | Full containerized deployment |
| `observability` | Prometheus + Grafana | Scrape backend HTTP metrics and view dashboards |

### Quick Docker Start

```bash
# Full deployment (all services)
make docker-up

# Infrastructure only (recommended for Apple Silicon -- use native Ollama)
make docker-infra

# Application only (use native Ollama + Docker Qdrant)
make docker-app

# Optional local metrics and Grafana (start with app or full profile too)
docker compose --profile app --profile observability up -d --build

# Stop everything
make docker-down
```

> **Apple Silicon note**: The Docker Ollama container uses CPU-only inference. For Metal GPU acceleration, run Ollama natively (`ollama serve`) and use Docker for Qdrant, or `docker-app` for the application services.

Docker deployment is a separate containerized web/infrastructure workflow. It
does not start the Tauri native host or provide the macOS meeting source-checkout
workflow; use `make dev-desktop` for that workflow.

### Docker Configuration

Docker uses `.env.docker` which differs from `.env.example` in:
- `OLLAMA_BASE_URL=http://ollama:11434` (Docker service name)
- `QDRANT_URL=http://qdrant:6333` (Docker service name)
- `COMFYUI_URL=http://host.docker.internal:8188` by default for host ComfyUI
- `AGENT_WORKSPACE_ROOT=/workspace`; set `AGENT_WORKSPACE_HOST_PATH` to a host project directory

### Exposed Ports

| Service   | Host Port | Container Port |
|-----------|-----------|----------------|
| Frontend  | 3000      | 3000           |
| Backend   | 8000      | 8000           |
| Qdrant    | 6333      | 6333           |
| ChromaDB (migration source) | 8100 | 8000 |
| Prometheus (optional) | 9090 | 9090 |
| Grafana (optional) | 3001 | 3000 |

The backend exposes request metrics at `/metrics`. Prometheus and Grafana are optional
and do not affect chat or meeting readiness. Change `GRAFANA_ADMIN_PASSWORD` before
using the observability profile beyond a local development machine.
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

External MCP server tools are automatically discovered at application startup, but remain operator-only. They are not exposed through authenticated HTTP routes or bound to shared-account agents because they do not enforce account ownership.

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
| `make clean-data`| Remove the root `data/` directory created by Make setup |

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
3. Restart the backend -- tools are discovered at startup and remain operator-only

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

### Meeting readiness is false / local ASR is unhealthy

The meeting gate requires the local `small.en` CTranslate2 model and the
application database. Inspect the required-only response:

```bash
curl -sS http://127.0.0.1:8000/api/v1/health/ready | python3 -m json.tool
```

Check that `backend/.env` contains `ASR_MODEL_NAME=small.en` and that
`ASR_MODEL_DIR` is an existing **absolute** directory named `small.en`. It must
be the complete CTranslate2 artifact, not a model name or its parent folder.
Provision/copy it before the meeting; the application intentionally does not
download ASR files during startup or a meeting. Also make sure the backend was
started from this checkout so it reads `backend/.env`.

### Full Xcode is not selected / Tauri build fails

If Cargo cannot find the macOS SDK or AVFoundation/ScreenCaptureKit frameworks,
check the selected developer directory:

```bash
xcode-select -p
xcodebuild -version
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -runFirstLaunch
```

The path must point to the full Xcode app, not
`/Library/Developer/CommandLineTools`. Then retry `make dev-desktop`.

### Microphone or system audio permission denied

In the Tauri window, use meeting preflight to request permissions or open
settings. In **System Settings → Privacy & Security**, enable **Microphone**
and **Screen Recording** for the debug/signed Local AI Application app. Return
to the app and use **recheck**; do not assume a previous request changed the
state. Screen Recording is required for the display-wide system-audio mix.

### Desktop launcher reports a port is already in use

The launcher intentionally refuses to adopt an unknown service on port 8000 or
3000. Inspect both ports, stop the process you recognize (usually with
`Ctrl-C` in its owning terminal), and retry:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
lsof -nP -iTCP:3000 -sTCP:LISTEN
```

Do not run `make dev` or manually start backend/frontend alongside
`make dev-desktop`. The launcher only stops process groups that it started.

### SQLite "Database is Locked"

This can happen with concurrent access. The application uses WAL mode and
busy_timeout to mitigate this. If you still see errors:

**Fix**: Ensure only one backend process is running. Check for stale `.db-wal`
and `.db-shm` files in `backend/data/`.

### Qdrant Connection Failed

```
Error: Could not connect to Qdrant
```

**Fix**: Verify Qdrant is running and accessible:
```bash
curl http://localhost:6333/healthz
```

For native development, ensure `QDRANT_URL=http://localhost:6333`; Docker uses
`QDRANT_URL=http://qdrant:6333`. Chroma remains available as a migration source.

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

**Fix**: Inspect the existing process and stop it from its owning terminal:
```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
lsof -nP -iTCP:3000 -sTCP:LISTEN
```

### RAG Search Returns No Results

If searches return empty despite having ingested documents:

- RRF scores are not cosine scores; inspect the returned `score_type` and use profile retrieval metadata
- Verify documents were ingested: check the collection count on the RAG page
- Try broader search queries

### Rate Limiting (429 Too Many Requests)

The API has rate limits to prevent resource exhaustion:

| Endpoint Type | Default Limit  |
|---------------|----------------|
| General       | 60/minute      |
| LLM-bound     | 10/minute      |
| File upload   | 20/minute      |

Adjust limits in `backend/.env` if needed for development.

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
| GET    | `/api/v1/health/ready`| Required meeting readiness check   |
| GET    | `/api/v1/health`      | System health check                |
| GET    | `/api/v1/tools`       | List all available tools           |

---

## Performance Tips

1. **Use native Ollama** on Apple Silicon for Metal GPU acceleration (not Docker).
2. **Use Q4_K_M quantized models** for the best speed/quality tradeoff on 8-16GB unified memory.
3. **Set `OLLAMA_NUM_PARALLEL=2`** for moderate concurrency. Don't exceed available memory.
4. **Batch RAG ingestion** -- ingest multiple documents before searching for best indexing performance.
5. **Keep prompts concise** -- local models perform best with focused, clear queries.
6. **Monitor memory** -- model residency depends on model size and context. Running chat and vision models simultaneously can use substantially more unified memory.

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
  backend/data/            # Runtime data used by local backend commands (gitignored)
    app.db                 # Chat history database
    demo.db                # SQL agent target database
    uploads/               # Uploaded documents
    chroma/                # Vector store
```
