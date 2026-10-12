# Library and runtime options for Local AI Application

Research date: 2026-10-11. Scope: Apple Silicon, local inference, no cloud API keys, and practical improvements to the current implementation. This is a research report; no dependencies or runtime code were changed.

## Recommended order

Start with SQLGlot and Trafilatura. Both address specific limitations through small changes. Benchmark MLX Whisper next because meeting transcription currently uses CPU inference. Evaluate Docling for difficult PDFs and newer embedding models for retrieval quality before considering a vector database migration.

| Priority | Candidate | Expected project benefit | Decision | Engineering estimate |
| --- | --- | --- | --- | --- |
| 1 | SQLGlot instead of sqlparse | More precise SQL policy checks and dialect-aware row limiting | Adopt after focused regression tests | 1–2 days |
| 2 | Trafilatura alongside BeautifulSoup | Cleaner article text and less irrelevant LLM context | Adopt if a saved-page evaluation passes | 0.5–1 day |
| 3 | MLX Whisper alongside faster-whisper | Test Apple GPU acceleration for meeting transcription | Benchmark first; retain CPU fallback | 1 day for experiment; 2–4 days for integration |
| 4 | Docling for complex/scanned PDFs | OCR, reading order, structured tables, and richer citation inputs | Add a bounded PDF path if quality improves | 1–2 days for experiment; 3–5 days for integration |
| 5 | New embedding models and existing Ollama features | Better retrieval and more reliable structured responses without a new runtime | Evaluate before larger replacements | 1–2 days, plus corpus re-embedding time |

These are estimates for one engineer familiar with the repository, including targeted checks. Expected benefits are engineering judgments, not measured improvements. The Mac's chip, RAM, representative documents, and acceptable meeting latency were not established. No local performance benchmarks were run.

## What the repository actually uses

The implementation differs from the architecture notes. `backend/pyproject.toml` does not include Unstructured. `document_parser.py` uses PyMuPDF for PDF text, pdfplumber for PDF tables, individual Office libraries, and BeautifulSoup for HTML. `ocr.py` constructs EasyOCR with `gpu=False`. PDF pages are joined into one text string; image OCR happens separately. The PDF path has no scanned-page OCR fallback, and its text metadata contains the file name and format rather than per-chunk page provenance.

`transcription.py` already provides a `TranscriptionEngine` boundary. The real engine loads an absolute, pre-provisioned CTranslate2 `small.en` directory with `local_files_only=True`, `device="cpu"`, and `compute_type="int8"`. It uses built-in VAD. This is a useful boundary for a controlled alternative; retain its offline readiness guarantees.

`web_tools.py` uses HTTPX to fetch HTML and removes selected tags with BeautifulSoup. `sql_tools.py` validates tokens with sqlparse, restricts statement count, and already handles outer LIMIT values rather than using a naive substring test. `vector_store.py` stores explicit Ollama embeddings in persistent Chroma collections and converts cosine distance to similarity. `embeddings.py` batches 32 texts per call. `llm.py` returns `ChatOllama`, and model listing and health checks use Ollama-specific endpoints. The orchestrator parses routing JSON with text/regex fallbacks.

The lockfiles already resolve substantially newer packages than the minimum versions in the architecture document:

| Area | Locked or declared version observed |
| --- | --- |
| Backend and orchestration | FastAPI 0.134.0; LangChain 1.2.10; LangGraph 1.0.10; langchain-ollama 1.0.1; MCP 1.26.0 |
| Documents and SQL | PyMuPDF 1.27.1; pdfplumber 0.11.9; EasyOCR 1.7.2; sqlparse 0.5.5 |
| Speech and retrieval | faster-whisper 1.2.1; CTranslate2 4.8.2; Chroma 1.5.2 |
| Frontend | Next.js 16.1.6; React 19.2.3; Zod 4.3.6; Zustand 5.0.11 |
| Desktop | Tauri 2; source-checkout development workflow; documented minimum macOS 13 |

Evidence: `backend/uv.lock`, `frontend/package.json`, `frontend/pnpm-lock.yaml`, and `desktop/README.md`. These are repository versions, not claims that they are the newest published releases. Keep FastAPI, LangGraph, Next.js, and Tauri: this investigation found concrete opportunities inside existing service boundaries, with no demonstrated gain from replacing the application frameworks.

## 1. SQLGlot: improve SQL policy expression

SQLGlot provides dialect-aware parsing, expression-tree inspection, and SQL generation. Its pure Python installation has no required dependencies and its code is MIT licensed. sqlparse describes itself as a non-validating parser. SQLGlot also explicitly warns that successful parsing does not prove a query is valid for a database: its parser is intentionally lenient. The benefit here is structural policy checks, not an automatic security guarantee. [SQLGlot documentation](https://github.com/tobymao/sqlglot), [sqlparse introduction](https://sqlparse.readthedocs.io/en/latest/intro.html).

**Integration surface:** `backend/app/tools/sql_tools.py:validate_query`, its callers, and `backend/tests/test_tools/test_sql_tools.py`. Pass the target dialect explicitly; inspect the complete tree for prohibited operations, including CTE bodies and dialect-specific write forms. Generate the row cap in that same dialect. PostgreSQL, SQLite, MySQL, and SQL Server should not all receive an unconditional trailing `LIMIT`.

**Tradeoff:** more explicit policy and dialect tests are necessary. An AST check must be backed by database read-only credentials or engine restrictions and execution timeouts; result limits do not bound the cost of a join. Keep SQLAlchemy as the executor. Do not introduce automatic transpilation or query optimization as part of this replacement.

**Acceptance check:** preserve existing safe SELECT results; reject multiple statements and writes; cover comments, quoted keywords, subquery limits, CTE writes, UNION, OFFSET, SELECT INTO, and unsupported statements. Exercise row limiting against each database dialect the project actually supports. Offline use requires no model download.

## 2. Trafilatura: improve website text extraction

Trafilatura extracts main text and metadata from supplied HTML. Its `extract` path combines its own rules with fallback extraction, with precision/recall controls. Current releases are Apache-2.0 licensed; versions before 1.8.0 used GPLv3+. These capabilities fit the current web tool's extraction function without replacing HTTPX. [Python usage](https://trafilatura.readthedocs.io/en/latest/usage-python.html), [extraction process](https://trafilatura.readthedocs.io/en/stable/extraction-overview.html), [license](https://github.com/adbar/trafilatura).

**Integration surface:** `extract_text_from_html` in `backend/app/tools/web_tools.py`. Run extraction on the HTML already fetched by HTTPX; use the present BeautifulSoup result when extraction returns no useful content. Keep BeautifulSoup for link discovery and HTML document parsing unless separately evaluated. Keep existing transport controls; a text extractor is not a replacement for URL validation or response-size handling.

**Expected benefit:** fewer navigation, cookie, and unrelated sidebar tokens in the bounded LLM context. Documentation pages and sparse pages may lose useful content under aggressive article extraction. It does not turn HTTP fetching into a JavaScript browser.

**Acceptance check:** use 20 saved pages covering articles, technical docs, sparse pages, tables, and navigation-heavy sites. Mark the text needed to answer one question per page. Compare retained answer text, irrelevant text, extraction time, and summary correctness. Local extraction needs no AI model or cloud account; downloading a live page still needs network access.

## 3. MLX Whisper: benchmark the smallest Mac speech change

The official MLX Whisper implementation accepts NumPy waveforms and a local directory of MLX-converted weights, returns segment details, and supports word timestamps. The MLX examples code is MIT licensed. Passing a Hub identifier can download a model, so an offline integration must require an explicit local path. [MLX Whisper usage](https://github.com/ml-explore/mlx-examples/tree/main/whisper), [transcription implementation](https://github.com/ml-explore/mlx-examples/blob/main/whisper/mlx_whisper/transcribe.py), [license](https://github.com/ml-explore/mlx-examples/blob/main/LICENSE).

**Integration surface:** a second implementation of `TranscriptionEngine` in `backend/app/services/transcription.py`, reusing PCM normalization and mapping segment times into `TranscriptionChunk`. Provision a separate MLX-format model directory; existing CTranslate2 files cannot be reused as MLX weights. Make readiness validate and load every required model/tokenizer artifact without downloads. Preserve bounded audio windows and close/cancellation behavior.

**Tradeoff:** MLX Whisper is not a drop-in match for faster-whisper's VAD behavior. Match silence handling, timestamps, language, decoder settings where possible, and test concurrent mic/system streams. GPU use competes with Ollama for shared memory and compute. A quicker isolated transcription run can still make simultaneous answer generation worse.

**Acceptance check:** compare the same `small.en` model family on identical saved meeting windows, including the application's default 2-second PCM windows: short questions, silence, noise, overlapping speech, and technical names. Measure cold load, p50/p95 final-transcript latency, real-time factor, word error rate, hallucinated silence text, timestamp drift, peak memory, and simultaneous Ollama response latency. The faster-whisper repository's GPU results are NVIDIA CUDA measurements and its CPU table uses an Intel processor; neither establishes a Mac speedup. [faster-whisper benchmark conditions](https://github.com/SYSTRAN/faster-whisper).

### Other speech candidates

**whisper.cpp:** MIT-licensed C/C++ implementation with Metal and optional Core ML encoder acceleration on Apple Silicon. It could be a better packaging path when Python runtime size becomes a measured problem, but introduces native build/model-format integration. ANEForge encoder support is now documented; its bundles are tied to the machine and OS build, and the decoder remains unchanged. Treat its encoder benchmark as an experimental opportunity, not an end-to-end meeting speed claim. Estimate 2–3 days for an experiment, 4–7 days for native integration. [whisper.cpp](https://github.com/ggml-org/whisper.cpp).

**WhisperKit:** the original repository now redirects to Argmax's MIT-licensed Swift OSS SDK. It includes an OSS local Audio API server and timestamp/streaming output; the Pro WebSocket server is a separate product. The documented OSS prerequisites include macOS 14 and Xcode 16. A Swift sidecar or native bridge adds lifecycle and packaging work and raises this project's documented macOS 13 floor. Estimate 2–3 days for an experiment and 5–8 days for integration. [Argmax OSS SDK](https://github.com/argmaxinc/argmax-oss-swift).

**Parakeet via MLX Audio or parakeet-mlx:** a worthwhile later model/engine experiment. MLX Audio documents Parakeet support; the NVIDIA v3 model card describes multilingual ASR and carries CC-BY-4.0 model terms. This changes both the model and implementation, so run it after the controlled Whisper comparison. File-result streaming does not establish compatibility with the project's live PCM windows. [MLX Audio](https://github.com/Blaizzy/mlx-audio), [NVIDIA model card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3), [parakeet-mlx](https://github.com/senstella/parakeet-mlx).

## 4. Docling: add a complex-PDF path

Docling represents layout, reading order, tables, OCR output, and document structure in a unified document model. Its code is MIT licensed; individual model licenses must be checked separately. Its official accelerator example includes macOS MPS configuration, and its offline guide supports explicit model prefetching and artifact paths. Native chunkers can include document metadata and refine chunks according to an embedding tokenizer. [Docling capabilities and license](https://github.com/docling-project/docling), [accelerator example](https://github.com/docling-project/docling/blob/main/docs/examples/run_with_accelerator.py), [offline setup](https://docling-project.github.io/docling/usage/advanced_options/), [chunking](https://docling-project.github.io/docling/concepts/chunking/).

**Integration surface:** `DocumentParserService._parse_pdf` and its `ParsedDocument` contract. Begin with scanned or complex PDF fixtures. Translate Docling tables into current table results and carry page/heading provenance into the RAG ingestion path. Merely exporting all Markdown into the present file-level splitter will discard much of the citation benefit. Retain the lightweight path for simple PDFs and current Office handlers during evaluation.

**Tradeoff:** model loading, bigger artifacts, peak memory, and conversion latency. Queue heavy conversions rather than running many parallel jobs alongside meetings. Prefetch selected models, disable remote services, and supply local tokenizer artifacts if adopting token-aware chunking. MPS configuration does not guarantee that every OCR component uses the GPU.

**Acceptance check:** 30–50 representative pages containing scanned text, two-column articles, merged-cell tables, rotated scans, and ordinary PDFs. Score missing text, reading-order errors, table-cell accuracy, page citation correctness, p95 conversion time, and peak memory. Compare downstream question answers as well as extracted text. Require the fully provisioned conversion to work with network disabled.

### Smaller OCR experiment and Marker comparison

`ocrmac` is a MIT-licensed Python wrapper for Apple's Vision framework. It returns text, confidence, and bounding boxes on macOS. This is a narrower experiment at `OCRService.extract_text` than replacing the full parsing stack, especially for screenshots and clean scans. Check language availability, ordering, and confidence handling; benchmark against CPU EasyOCR rather than assuming better accuracy. Estimate 0.5–1 day for an experiment, 1–2 days for integration. [ocrmac](https://github.com/straussmaximilian/ocrmac).

Marker 2.0's release notes describe selective OCR and device-aware fast/balanced modes, including CPU/MPS defaults. Its published throughput measurements use B200 hardware and do not establish this Mac's performance. The project currently licenses its code under Apache-2.0, while its model weights use modified terms limited to research, personal use, and qualifying startups under $5 million funding/revenue without a commercial license. Do not make it the default under a broadly free-use requirement until the exact weight terms fit intended distribution. Keep hybrid external-LLM services disabled or explicitly local. [Marker release notes](https://github.com/datalab-to/marker/releases), [current capabilities and terms](https://github.com/datalab-to/marker), [model license](https://github.com/datalab-to/marker/blob/master/MODEL_LICENSE).

## 5. Improve retrieval and output reliability before replacing Ollama

Two current Ollama embedding candidates are `embeddinggemma` and **explicitly** `qwen3-embedding:0.6b`. Ollama lists EmbeddingGemma at about 622 MB and requiring Ollama 0.11.10 or newer; the Qwen 0.6B artifact is about 639 MB. The unqualified Qwen tag resolves to an 8B artifact around 4.7 GB. These are download sizes, not peak RAM requirements. [EmbeddingGemma in Ollama](https://ollama.com/library/embeddinggemma), [Qwen embeddings in Ollama](https://ollama.com/library/qwen3-embedding).

Qwen's 0.6B model card specifies Apache-2.0. EmbeddingGemma uses Gemma terms, and direct Hugging Face access requires accepting those terms. Query/document instructions and output dimensions differ across models; follow the selected model card. [Qwen model card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B), [Google model card](https://huggingface.co/google/embeddinggemma-300m).

**Integration surface:** `backend/app/services/embeddings.py`, `vector_store.py`, and current model settings. Re-embed into a separate collection with the model/version and dimension recorded. Do not mix embedding spaces even when dimensions happen to match. Recalibrate the current cosine threshold instead of carrying over 0.7. Start with the existing chunking strategy so model effects are measurable separately from parser changes.

**Acceptance check:** 50–100 labeled questions over the actual corpus. Include exact identifiers, table questions, paraphrases, and relevant languages. Compare recall@5, reciprocal rank, wrong-source retrieval, citation correctness, embedding throughput, warm-query latency, and peak memory. Keep nomic if newer models do not improve the local task. Both alternatives require model downloads before offline evaluation.

Ollama's structured outputs accept JSON schemas and its examples validate resulting data with Pydantic. Use this for orchestrator routing and extraction contracts, retaining application validation and graceful errors. Its FAQ also documents local-only mode via `OLLAMA_NO_CLOUD=1` and performance controls for Flash Attention and KV-cache quantization. Apply runtime environment settings to the Ollama server process; placing them only in the FastAPI `.env` does not configure an independently running Ollama service. Cache quantization can affect quality, so benchmark it before enabling it. [Structured outputs](https://docs.ollama.com/capabilities/structured-outputs), [Ollama FAQ](https://docs.ollama.com/faq).

### MLX LM versus Ollama

MLX LM is a MIT-licensed Apple Silicon text-generation package with quantization, prompt caching, and configurable memory/prefill controls. It is a credible runtime benchmark candidate. It is not a drop-in `ChatOllama` replacement, and text generation alone does not replace this project's vision, embedding, tool-call, model-listing, or health behavior. [MLX LM](https://github.com/ml-explore/mlx-lm).

Compare equivalent model families, quantization, prompt lengths, and generation settings using local artifacts. Measure first-token time, tokens/second, tool-call correctness, structured-output validity, cancellation, and combined ASR/chat load. Only add a second provider if a measured gain justifies its lifecycle and API work. Estimate 1–2 days for a standalone benchmark and 4–7 days for a feature-equivalent provider integration; these estimates exclude model conversion problems. Keep Ollama as the default during research.

## Vector database replacements: conditional

LanceDB OSS is an embedded local retrieval library licensed under Apache-2.0. Its hybrid-search API combines vector and full-text queries, supports explicit precomputed vectors, and uses reciprocal rank fusion by default. It could improve exact identifier retrieval while retaining Ollama embeddings. These are functionality reasons to test it, not proof that it is smaller or faster than this project's Chroma installation. [LanceDB OSS](https://github.com/lancedb/lancedb), [hybrid search](https://docs.lancedb.com/search/hybrid-search).

Qdrant's Apache-2.0 Python client supports persistent local mode without a server; its documentation positions local mode for development/prototyping/testing and switching to server mode for scaling. The self-hosted server provides hybrid-query facilities, but adds process and storage operations to this desktop workflow. Do not treat Python local mode as the production server's performance profile. [Qdrant client](https://github.com/qdrant/qdrant-client), [self-hosted server](https://github.com/qdrant/qdrant), [hybrid queries](https://qdrant.tech/documentation/search/hybrid-queries/).

**Integration surface:** preserve the `VectorStoreService` methods and external result schema. Migrate IDs, text, metadata, vectors, collection operations, filtering, and deletion semantics. Handle differences in raw distances and hybrid scores; an RRF score cannot reuse the current cosine threshold. Use copied data for experiments and retain the original Chroma store.

**Decision gate:** first measure where current retrieval fails. If exact names and codes are the issue, compare a lexical+vector baseline against a LanceDB prototype. Use identical embeddings and chunks, then test 10,000 and 100,000 chunks if representative. Measure recall, p95 latency, RAM, disk use, ingestion, deletion, and restart integrity. Estimate 1–2 days for a comparative prototype and 3–5 days for a migration with rollback. No evidence gathered here justifies migrating today.

## New runtime watchlist: BaseRT

BaseRT's July 21, 2026 paper reports substantial prompt-processing gains on an M5 Pro. Those are the authors' measurements under their model/hardware conditions, not results for this application. Its repository distinguishes Apache-2.0 tooling/bindings from a separate **proprietary prebuilt inference engine**, and documents macOS 14+ requirements. It does not satisfy an entirely open-source replacement requirement without changing project policy. Keep it off the adoption shortlist; revisit only if engine licensing and target hardware justify it. [Paper and date](https://arxiv.org/abs/2607.19438), [repository and license boundary](https://github.com/basecompute/baseRT).

## Small, reviewable next milestone

Evaluate SQLGlot against the existing SQL test corpus and explicitly selected database dialects. Keep this milestone separate from parser, model, or vector-store changes. The checkable outcome is clearer SQL policy with preserved safe query behavior and row caps, not an assumed speedup.

Research verification: inspected dependency manifests/lockfiles and relevant service implementations; checked primary documentation, repositories, model cards, and release notes. No packages installed, benchmarks executed, or application behavior changed. Published benchmark figures and rankings were not treated as local performance evidence. Before implementation, pin exact package and model revisions and run the component's acceptance check on the intended Mac.
