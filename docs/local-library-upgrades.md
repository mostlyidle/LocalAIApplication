# Local library upgrades

The SQL and web improvements are enabled directly. MLX Whisper and Docling are optional
backends that require local model provisioning. Existing CPU speech, lightweight PDFs, and
nomic embeddings remain the defaults while you evaluate accuracy, latency, and memory use.

## Install

From `backend/`, run `uv sync --extra dev --extra mlx --extra documents`. The MLX extra is
Apple Silicon only. `backend/.python-version` selects Python 3.12 because the locked Chroma
release still imports Pydantic v1, which does not support Python 3.14.

The locked MLX 0.32.3 binary wheels target **macOS 26 or later**. Keep the default
faster-whisper backend on older macOS, and omit `--extra mlx` when installing there. This
optional feature does not raise the desktop host's macOS 13 floor for the CPU workflow.
Earlier MLX releases may support older macOS, but they were not verified in this change.
MLX also requires access to a Metal device. Omit the MLX extra in a headless or restricted
environment without GPU access; the default CPU workflow does not need it.

## SQL and web

SQLGlot checks the full query tree, including CTE bodies, rejects write/locking forms in
read-only mode, and generates row limits in the selected connection's dialect. SQLite uses
`query_only`; PostgreSQL uses a read-only transaction. For other engines, configure a database
account with read-only permissions. SQL parsing is not a security sandbox or proof that a
database accepts a query. `SQL_QUERY_TIMEOUT_SECONDS` defaults to 30 seconds; driver-side
statement timeouts remain advisable because cancelling an await cannot stop every driver.

Trafilatura extracts main text from fetched HTML, with the existing BeautifulSoup extractor
as the fallback for sparse pages. HTTPX fetching and link discovery are unchanged.

## MLX Whisper

Provision an MLX-converted Whisper model before starting the application. For example,
`hf download mlx-community/whisper-small.en-mlx --local-dir /absolute/path/to/mlx-small.en`.
The directory must contain `config.json` and `model.safetensors`, `weights.safetensors`, or
`weights.npz`. This provisioning command uses the network; meeting runtime does not download
weights. CTranslate2 weights from faster-whisper are not interchangeable with MLX weights.

In `backend/.env`, set:

```env
ASR_BACKEND=mlx-whisper
ASR_MODEL_DIR=/absolute/path/to/mlx-small.en
```

Restart the backend. Existing meeting readiness checks load the selected engine. Missing
artifacts or dependencies fail readiness with an actionable error. No automatic fallback
attempts to interpret one engine's files as another format. To return to CPU speech, select
`ASR_BACKEND=faster-whisper` and point `ASR_MODEL_DIR` at the provisioned CTranslate2 directory
whose basename is `small.en`.
After a failed native MLX load, fix the cause and restart the backend. The failed load is
cached to prevent repeated initialization of a partially loaded native extension.

MLX inference is serialized across sources and remains serialized when an awaiting task is
cancelled. Its silence detection differs from faster-whisper's VAD. Evaluate the default
2-second windows, noisy speech, silence, timestamps, and simultaneous Ollama responses.

## Docling

Provision layout, table, and English OCR weights before offline use. From `backend/`:

```python
from pathlib import Path
from docling.utils.model_downloader import download_models

download_models(
    output_dir=Path("/absolute/path/to/docling-models"),
    with_code_formula=False,
    with_picture_classifier=False,
    with_rapidocr=False,
    with_easyocr=True,
)
```

Run that snippet in a Python process with network access during setup. Then configure:

```env
PDF_PARSER=docling
DOCLING_ARTIFACTS_PATH=/absolute/path/to/docling-models
```

Restart the backend. The PDF path disables remote services and OCR downloads, limits files
to the existing upload size, limits documents to 1,000 pages, and sets a 120-second conversion
budget. Conversions run one at a time per parser instance. Failed or partial conversions are
reported instead of silently ingesting incomplete output. A timed-out Python await does not
terminate a native worker; the worker lock continues protecting subsequent conversion work.

Both PDF backends now retain page provenance. Docling also retains section headings and
rendered table text. API and tool/MCP ingestion chunk those blocks separately, preserving
page and section metadata. Existing indexed documents need re-ingestion into a new collection
to acquire the new provenance. Set `PDF_PARSER=pymupdf` to use lightweight parsing again.

## Embeddings and structured responses

Keep `OLLAMA_EMBEDDING_MODEL=nomic-embed-text` to preserve the current input format. To
evaluate a new model, provision it with `ollama pull qwen3-embedding:0.6b` or
`ollama pull embeddinggemma`. Set the chosen model in `backend/.env`, choose a **new**
`CHROMA_COLLECTION_NAME`, restart the backend, and ingest the documents into that collection.
The RAG page has its own collection selector/input; use the same new name there. Original
collections remain available when using their original embedding model.

Qwen queries receive an instruction; EmbeddingGemma uses distinct query and document
prefixes. Existing nomic input is intentionally unchanged. New collections record the model
tag, installed weight digest, input profile version, and vector dimension. A changed model,
digest, profile, or dimension is rejected before writing/querying vectors. Model identity is
also checked before and after embedding operations to detect a concurrent model update.

Legacy nonempty collections have no identity metadata. They remain usable with the original
default `nomic-embed-text` model, but their historical weights cannot be verified. Do not switch
their model. Re-ingest them into a new named collection to acquire verifiable provenance.
Re-ingestion upserts stable chunk IDs; if the document or chunking changes, use a new collection
to avoid leaving stale trailing chunks from an earlier version. Calibrate `RAG_SCORE_THRESHOLD`
against labeled questions for each model; a threshold of zero is now honored.

Ollama receives the Pydantic router JSON schema. Invalid responses fall back to chat; raw text
and Markdown wrappers are no longer guessed into specialist routes. Pydantic still validates
the returned JSON. Existing tool schemas continue to structure specialist tool arguments.

For local-only mode and cache tuning, set these variables on the **Ollama process**, not only
in the backend `.env`:

```sh
OLLAMA_NO_CLOUD=1 OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 ollama serve
```

If Ollama already runs as a macOS app, follow its documented environment setup and restart
that app rather than launching another server on its port. Cache quantization affects the
KV cache rather than halving the application's total RAM; evaluate quality with the intended
chat model before enabling it globally. No running user Ollama configuration was modified.

## Repeatable checks

From `backend/`, compare local speech engines on a signed-16 PCM WAV:

```sh
uv run --extra mlx python -m app.benchmark asr sample.wav \
  --cpu-model-dir /absolute/path/to/cpu/small.en \
  --mlx-model-dir /absolute/path/to/mlx-small.en \
  --reference transcript.txt
```

The default is 2,000 ms windows and three passes. Reports include load time, p50/p95 window
latency, real-time factor, and optional word error rate. Neither engine downloads models.
Run engines without unrelated GPU activity first, then repeat with concurrent chat to inspect
shared-memory contention. These metrics include each first inference, not only warmed kernels.

To compare retrieval, create a UTF-8 JSON dataset:

```json
{
  "documents": [{"id": "invoice", "text": "Invoice INV-42 totals 123 dollars."}],
  "questions": [{"query": "What is the total for INV-42?", "relevant_ids": ["invoice"]}]
}
```

Run `uv run python -m app.benchmark embeddings corpus.json`. Models must already be installed
in local Ollama. The comparison embeds in memory and reports recall@5, mean reciprocal rank,
ingestion time, query latency, dimensions, and model digests. It never mutates Chroma. Use
50–100 labeled questions from representative documents for an adoption decision; a tiny
synthetic corpus verifies integration only.

## Verification performed

Checks ran on Apple M1 Pro with macOS 27.0.1, Python 3.12, and the locked dependency versions.

Real offline CPU and MLX inference passed using the same `small.en` model family and the
public whisper.cpp JFK clip. With two-second windows and three passes, CPU median/p95 latency
was 711/807 ms; MLX was 220/269 ms. Word error rate on the first pass was 18.2% versus 4.5%.
The engines use their respective decoder/precision defaults; these numbers are not a pure
hardware-only comparison. Full-clip inference instead took 2.10 seconds on CPU and 2.68 on
MLX, illustrating the importance of the application's actual window size.

Docling recovered text from a synthetic two-page PDF containing a scanned page, retained
page-2 citations, and completed cold conversion in 24.3 seconds with network access disabled.
The three embedding models each returned correct first-ranked passages for eight synthetic
questions. That small corpus cannot establish production retrieval quality or superiority.
Schema-constrained routing also passed against a real local chat model. Tests used an isolated
local-only Ollama server on port 11435 with temporary model storage and q8_0 cache settings.

Model artifacts and benchmark inputs were provisioned in task-specific `/private/tmp/` folders;
normal app settings, uploads, and existing indexes were not changed. Production meeting,
large-document, memory-pressure, and Windows hardware checks remain deployment gates.
