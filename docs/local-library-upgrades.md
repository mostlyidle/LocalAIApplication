# Local library upgrades

The SQL and web improvements are enabled directly. MLX Whisper and Docling are optional
backends that require local model provisioning. Existing CPU speech, lightweight PDFs, and
nomic embeddings remain the defaults while you evaluate accuracy, latency, and memory use.

## Install

From `backend/`, run `uv sync --extra dev --extra mlx --extra documents`. The MLX extra is
Apple Silicon only. `backend/.python-version` selects Python 3.12 because the locked Chroma
release still imports Pydantic v1, which does not support Python 3.14.

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
