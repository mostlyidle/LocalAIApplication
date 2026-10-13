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
| Focused verification | Complete | Frontend 53 focused tests, including recursive folder-drop path coverage; TypeScript, and backend focused tests/lint pass. ESLint reports one existing `<img>` warning in `ChatWindow.tsx:583`. |
| Browser E2E | Picker/index/search complete; native folder drop unconfirmed | Safari 27.0.1 on macOS 27.0.1: folder selection staged root and nested files with relative paths, indexed both through live Qdrant/Ollama, and search returned their fixture text. Finder-to-Safari drag attempts did not produce a browser drop event in UI automation; the focused Vitest test passes for recursive directory entries and paths. The RAG chat profile's index selector listed the container. Chat generation not tested; default `qwen2.5:7b` is not installed. |
| Deployment database migration | Verified on deployment schema | `.env.docker` configures the app database as SQLite in the persistent `/app/data` volume. A disposable SQLite database upgraded from revision `20261012_23` to head `20261012_24`; an existing collection remained intact and the new file table/index were created. The live deployment volume was not accessed. |
| Checkpoint commit and push | Complete | Backend and frontend checkpoints are pushed to `origin/feature/vector-index-containers`. |

**Current result:** implementation, focused verification, and Safari folder picker/index/search
flow are complete. The folder picker fix removes the `accept` hint from the directory input only;
regular file selection keeps its filter. Migration passed against a disposable database using the
deployment's SQLite schema. Native Finder drag-and-drop still needs a manual Safari check because
the UI automation did not deliver the OS folder drag to the browser.

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
- Browser E2E (2026-10-13, Safari, isolated local app/database): created `Browser E2E Index`
  and `Browser E2E Isolation`; uploaded and indexed `amberfield.txt` and `copper-finch.txt`
  into separate live Qdrant collections using local Ollama embeddings. Searches in each
  selected index returned that index's own note. The RAG chat profile exposed both containers
  and accepted switching the selected index. Chat generation was not tested because its
  default `qwen2.5:7b` model was not installed.
- Minimal Safari picker A/B (Safari 27.0.1/macOS 27.0.1): plain
  `<input type="file" webkitdirectory multiple>` selected the fixture folder and returned both
  files with correct `webkitRelativePath`; adding the app-style `accept` filter left Upload
  disabled. See [Safari folder picker research](research/safari-folder-picker.md).
- Safari folder-picker regression E2E (2026-10-13, fresh temporary account/database and Qdrant):
  created `Folder Picker Regression E2E`, selected a folder with `root-note.txt` and
  `reference/nested-note.txt`, and saw both staged as `knowledge-base/root-note.txt` and
  `knowledge-base/reference/nested-note.txt`. Both indexed successfully (2 files, 2 chunks);
  search returned the expected `Copper Finch` and `amberfield` fixture passages. The RAG chat
  profile's Search index selector exposed the container. Chat generation remains untested because
  its configured `qwen2.5:7b` model is not installed.
- Folder-drop regression and deployment-schema migration check (2026-10-13): focused Vitest coverage
  passed for a dropped directory with root/nested files and preserved relative paths. Finder-to-
  Safari native drag attempts did not visibly reach the browser drop handler, so native drag remains
  unconfirmed. Disposable SQLite upgrade from `20261012_23` to `20261012_24` passed with a seeded
  existing collection; the live Docker volume was not touched.

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

- Safari folder picker fix is applied: the directory input no longer has an `accept` attribute;
  the regular file input retains its filter. Folder selection and relative-path preservation pass
  in Safari. Hidden-file behavior is not separately verified. Backend format validation rejects
  unsupported files individually.
- Native Finder folder drag into Safari remains unconfirmed; run a manual check where Finder and
  Safari are visible together. Deployment SQLite migration is verified using a disposable database;
  no live database volume was modified.

## Rough estimate

The initial estimate is superseded by implementation progress above. Remaining work is
focused verification, review, and checkpointing.
