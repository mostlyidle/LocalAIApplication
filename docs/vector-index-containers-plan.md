# Vector index containers plan

## Status

Implementation in progress on `feature/vector-index-containers` (2026-10-13). The user
approved implementation and checkpoint commits/pushes. Continue from the stage notes below;
do not restart planning or create another feature branch.

### Stage notes

| Stage | Status | Notes |
| --- | --- | --- |
| Plan and boundaries | Complete | User approved private per-account containers and the in-app parser/embedding path. |
| Backend schema and APIs | Complete | Migration, ownership checks, staged uploads, explicit load/retry/remove/delete routes are implemented. |
| Durable ingestion | Complete | A database-backed polling worker claims files with a lease, retries up to five times, and reuses app parsing, chunking, Ollama embeddings, and Qdrant. |
| Container UI | Complete | Create/select containers; choose or drop files/folders; review per-file statuses; load, retry, remove, and delete. UI followed `ui-ux-pro-max`. |
| Search and chat selection | Complete | Both surfaces select private containers or existing app collections and pass the selected index through existing retrieval. |
| Focused verification | Complete | Frontend 52 focused tests, TypeScript, and backend focused tests/lint pass. ESLint reports one existing `<img>` warning in `ChatWindow.tsx:583`. |
| Checkpoint commit and push | Complete | Backend and frontend checkpoints are pushed to `origin/feature/vector-index-containers`. |

**Current result:** implementation and focused verification are complete. The feature branch
is ready for review. Before release, check directory selection/drop behavior in the supported
browsers and run the migration against the deployment database backend.

**Checkpoint history:**

- `c977962 feat: add private RAG container backend` — pushed.
- `c7a9e45 feat: add RAG container management UI` — pushed.

**Latest verification:**

- Backend: `./.venv/bin/pytest tests/test_api/test_rag_containers.py tests/test_api/test_rag_routes.py tests/test_api/test_documents_routes.py tests/test_services/test_migration_sequence.py -q` — 40 passed.
- Backend Ruff on changed feature files — passed.
- Frontend: `vitest run` for `ContainerManager`, the RAG page, and chat — 52 passed.
- Frontend `tsc --noEmit` — passed.
- Frontend ESLint on changed UI/API files — 0 errors, 1 `<img>` warning at `ChatWindow.tsx:583`.
- `git diff --check` — passed.
- The backend integration tests use SQLite and mock Qdrant; a live Qdrant server was not available for its client-version warning.

### Implementation choices made

- A container is a `RagCollection` ownership record with a generated internal name and a
  unique, account-private display name. Its Qdrant collection is created on first indexing.
- Uploaded content uses existing app document storage. Unlinking a file or deleting its
  container keeps uploaded source documents in Documents.
- The server accepts batches of up to 100 files / 500 MiB and preserves relative folder
  paths. Per-file size/type checks reuse the existing upload rules (50 MiB per file).
  The browser sends batches of at most 100 files / 400 MiB.
- Load is explicit. The durable worker uses persisted per-file state and a one-hour lease;
  retries use bounded exponential backoff and stop after five attempts. Repeated writes use
  stable chunk IDs to avoid duplicating vectors after a restart.
- `rag-dataloader` remains its separate bulk pipeline. Its FastEmbed collections are not
  offered as app-managed containers because their embedding identity differs.

## User goal

Let each signed-in user create named containers that represent separate vector indexes,
add many files or folders, and load their contents into the app's vector database. Users
should be able to search or chat against one selected container without mixing its
results with another container.

## What exists today

- `LocalAIApplication` owns document upload, format validation, parsing, chunking,
  embedding, Qdrant writes, hybrid retrieval, and account ownership checks.
- The RAG page supports one-document-at-a-time ingestion into a typed collection name.
- `RagCollection` records which account owns app-managed collections.
- The app's document parser handles its configured PDF, Office, text, CSV, HTML, and
  image formats. Upload limit defaults to 50 MB per file.
- RAG search and chat accept collection names; chat currently uses a text field.
- `rag-dataloader` is a separate resumable CLI pipeline for large directory syncs. It
  uses FastEmbed and its own Qdrant collection ownership and query-embedding contract.

## Proposed first version

1. **Create private containers.** Add a named container flow to the RAG page. Reuse the
   existing collection ownership registry where practical, with a generated internal
   collection ID and user-facing display name. Creating a container claims its private
   registry record; Qdrant collection can be created when first indexed.

2. **Stage files and folders.** Accept multiple files and folder selection/drop. Upload
   files into existing app-owned document storage and associate them with the selected
   container. Preserve relative folder paths for display and source citations. Keep
   keyboard-accessible file/folder chooser alongside drag and drop. Report unsupported
   files and upload failures individually; never silently skip them.

3. **Load and track progress.** Add a load action for a container. Use existing parser,
   chunker, Ollama embedding service, and Qdrant write path. Persist per-file state and
   ingestion job progress so refreshes and backend restarts do not lose results. Show
   queued, processing, indexed, and failed counts with per-file retry. Skip unchanged
   indexed files; update changed files without duplicating their vectors. Keep file count
   distinct from vector chunk count.

4. **Select index for retrieval.** Replace free-text collection entry in RAG search and
   RAG chat with account-scoped container selectors. Pass selected collection through
   existing retrieval requests. Deleting a staged file should remove its vectors only
   from the associated container. Confirm container deletion before deleting its Qdrant
   data and membership records.

5. **Apply UI design guidance.** Use the `ui-ux-pro-max` skill when designing and
   implementing the container, upload, progress, error, and retrieval-selection UI. Apply
   its accessibility, responsive layout, touch target, and interaction feedback guidance.

6. **Verify and checkpoint.** Cover ownership isolation, upload validation, folder paths,
   persisted state, retries, idempotent loads, per-file removal, deletion, and search/chat
   isolation. Run focused backend and frontend checks. Commit and push verified
   milestones to `feature/vector-index-containers` after branch creation.

## Important boundary

Keep `rag-dataloader` as a supported bulk-ingestion workflow. Its FastEmbed vectors and
query prefixes differ from the app's Ollama embedding path; vectors from those pipelines
must not be written into or queried as though they share an embedding identity. Existing
loader-owned collections remain read-only to app ingestion and need a compatible query
path before offering them as selectable app containers.

## Success criteria

- One account can create two containers and load different folder contents into each.
- Another account cannot list, search, mutate, or delete those containers.
- Search and RAG chat return evidence only from the selected container.
- Reloading the page or restarting the backend preserves staged files and load status.
- Retrying a failed or interrupted load does not duplicate successfully indexed chunks.

## Decisions already supplied by user

- Containers are private per signed-in account.
- Checkpoint commits and pushes are approved for implementation.
- Feature branch `feature/vector-index-containers` is approved because repository
  instructions prohibit commits directly to `main`.
- The user reviewed the plan and then approved implementation.

## Open implementation details

- Check folder selection/drop behavior in the supported browsers, including which hidden
  files the browser exposes. The file chooser filters by existing supported formats; every
  received unsupported file gets an individual failure result.
- Verify the database migration against the repository's supported database backends.
- Check how the directory chooser and folder-drop expose hidden files in supported browsers.
  The implementation uses browser `webkit*` directory APIs; this compatibility was not
  verified during the focused checks.

## Rough estimate

The initial estimate is superseded by implementation progress above. Remaining work is
focused verification, review, and checkpointing.
