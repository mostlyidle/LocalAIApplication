# Full project review fixes

## Resume context

- Request: implement every item from the full project review at `fb69f24`, following `$ponytail` and `$mattpocock-skills:tdd`.
- Repository: `/Users/lipdevs/code/AI/LocalAIApplication`.
- Starting branch and commit: `feature/agent-prompt-management` at `fb69f24c9da3d0896acc41bba0fc6da5812b575f`.
- Starting tree was clean and branch tracked `origin/feature/agent-prompt-management`.
- User previously authorized verified checkpoint commits and pushes on the feature branch. Do not commit directly to `main`, rewrite history, or change repository administration.
- Work in vertical red/green slices. User approved all seven public test seams on 2026-10-14.
- Read `AGENTS.md`, ponytail skill, TDD skill, and its `tests.md` and `mocking.md`. No `GLOSSARY.md` or ADR files were found.
- Do not rerun the original project-wide suite until targeted fixes are done; baseline was 803 backend passes / 5 failures, 342 frontend passes, TypeScript passed, and 19 distinct native tests passed after rerunning the socket tests with local-socket permission.
- Keep this file current with implementation decisions, test results, commits/pushes, and any findings that prove not to reproduce. At the start of a resumed session, check `git status`, current branch, this note, and applicable `AGENTS.md` before proceeding.

## Proposed public test seams

1. Authenticated REST and WebSocket behavior for ownership, quotas, prompt/profile selection, and conversation state.
2. Document upload, analysis, parsing, ingestion, and deletion behavior.
3. Public service behavior for memory, meeting retrieval/audio processing, SQL execution, and RAG.
4. MCP client discovery/invocation and app startup.
5. Rendered frontend interactions for chat attachments, settings selection, and resource switching.
6. Desktop worker/transport behavior for stop/drain and audio formats.
7. Make/setup configuration behavior.

These cover caller-visible behavior. They do not prove real Ollama response quality or physical Windows/macOS capture hardware.

## Findings checklist

### P1

- [x] 01. Chat's document agent binds raw path tools; unlike `/tools/execute`, it does not verify ownership or an upload root. Restrict all four document tools to the authenticated user's resolved attachment paths; retain existing parser callers for already-authorized upload flows (`backend/app/tools/document_tools.py`, `backend/app/agents/document_agent.py`).
- [x] 02. Chat state omits `database`, so model tool arguments can choose any process-global SQL engine. Force the configured default for chat tool calls; explicit `/sql/query` must keep its authorized selected database (`backend/app/agents/sql_agent.py`).
- [x] 03. Account ownership of a connection name does not stop an account registering a SQLite URL to the app's own database and reading other accounts' rows. Reject registrations resolving to the app database while keeping supported external/local target databases (`backend/app/api/routes/sql.py`).
- [x] 04. Optional meeting answers call the default/global RAG collection without the meeting owner's access context. Carry the authenticated meeting owner into retrieval and use normal collection access checks; preserve the setting-off behavior (`backend/app/services/meeting_answers.py`, `backend/app/services/meetings.py`).
- [x] 05. Hybrid retrieval lazily creates a built-in-only registry and prompt store, separate from the lifespan-configured registry. Use the configured single existing agent type/profile source for custom RAG retrieval and query rewriting (`backend/app/services/hybrid_vector_store.py`, app startup wiring).
- [x] 06. If a consumer raises, the processor worker exits with accepted queue items unfinished; `stop()` waits forever at `queue.join()`. A failed session must settle unfinished items and discard unsafe partial buffers before stop/purge completes (`backend/app/services/meeting_processor.py`). Final-flush failures now mark the session failed, drain queued work, clear buffers, and cancel the worker; `fail()` and `abort()` also clear buffers.

### P2

- [x] 07. A renamed copy of the document specialist takes the generic graph path, which drops its asset context and bypasses `TaskRunner`; the UI also checks a literal built-in name. Preserve source profile execution based on its behavior/target (`backend/app/api/routes/chat.py`, frontend chat).
- [x] 08. `/sql/query` directly invokes `sql_agent_node` without configured saved system prompts, so the SQL page ignores Settings overrides (`backend/app/api/routes/sql.py`).
- [x] 09. Auto-RAG estimates room using the on-disk base prompt, then replaces it with a potentially much longer saved override. Include the effective override in context budgeting (`backend/app/agents/rag_agent.py`).
- [x] 10. `execute_query` returns successful write-mode results from an uncommitted session, which rolls back on close. Commit only when writes are enabled; keep read-only behavior (`backend/app/tools/sql_tools.py`).
- [x] 11. `asyncio.timeout` cancels the coroutine but does not interrupt the aiosqlite worker query; cleanup waits for it. Interrupt the driver operation at the deadline (`backend/app/tools/sql_tools.py`). Execution now runs in a task, interrupts the SQLite driver before cleanup, then settles the task; a real recursive SQLite query regression stays within the deadline.
- [x] 12. App SQLite connections enable WAL and busy timeout but not foreign keys; deleting a conversation leaves DB-only child rows such as recall summaries. Enable `PRAGMA foreign_keys=ON` (`backend/app/services/database.py`).
- [x] 13. Document deletion cleans container memberships but leaves vectors created through legacy `/rag/ingest`, which has no memberships. Remove all indexed content for the owned document without crossing collection access boundaries (`backend/app/api/routes/documents.py`).
- [x] 14. Image parsing returns a filename placeholder and `requires_ocr`; no downstream consumer performs OCR before analysis/ingestion marks it complete. OCR must feed the actual text path (`backend/app/services/document_parser.py`, existing OCR service callers).
- [x] 15. DOCX table cells are extracted separately from `ParsedDocument.text`; chunking and `TaskRunner` analyze text only, so table-only documents yield no useful RAG chunks. Include table content once in text/blocks (`backend/app/services/document_parser.py`).
- [x] 16. Context loading exits when `memory_enabled` is false before checking independent `past_chat_recall_enabled`; vector search has the same coupling. Respect both controls independently (`backend/app/services/memory_context.py`, memory index callers).
- [x] 17. Memory PATCH validation checks nullable values instead of supplied fields: `project_scope: null` cannot clear scope, while `content: null` reaches `.strip()` and returns 500. Validate explicit nulls against required/optional fields (`backend/app/models/memory_schemas.py`, route caller).
- [x] 18. The send button is disabled during upload, but Enter invokes `handleSubmit` without checking uploads, clearing pending attachments before their upload IDs exist (`frontend/src/components/chat/ChatWindow.tsx`).
- [x] 19. Document Analyze UI sends a question in a JSON body, but the endpoint accepts no body and returns extraction only. Make the question part of the analysis or remove the misleading prompt field (`backend/app/api/routes/documents.py`, frontend caller).
- [x] 20. `refreshAgents` depends on selected name and unconditionally copies fetched prompt into the editor; selecting a profile triggers another async refresh that can overwrite newer edits/selection (`frontend/src/app/settings/page.tsx`).
- [x] 21. Async resource refreshes can resolve out of order: older RAG container files replace current selection; SQL schema can show a previous connection. Ignore stale responses (`frontend/src/components/rag/ContainerManager.tsx`, `frontend/src/components/sql/SchemaBrowser.tsx`). RAG load, retry, and removal callbacks now verify that their container is still selected before refreshing files or parent data, including stale-error handling.
- [x] 22. Conversation `updated_at` changes on title/summary edits but not an ordinary later turn, while lists sort on it. Touch activity on each persisted turn (`backend/app/api/routes/chat.py`).
- [x] 23. SQLite strips timezone info from persisted UTC datetimes; API emits naive strings while new live messages emit `Z`, so clients interpret reloaded times as local. Serialize persisted timestamps as UTC-aware (`backend/app/api/routes/chat.py` and response callers).
- [x] 24. ASR chunk timestamps are relative to each PCM window, so timestamps restart each window. Add the source's preceding audio duration before persistence/events (`backend/app/services/meetings.py`). The processor now preserves per-meeting, per-source consumed samples across reconnects and clears the timeline on terminal stop/failure.
- [x] 25. Desktop Stop sends terminal control before draining native queued/pending PCM, silently losing captured audio under backpressure. Stop capture and flush queued frames before terminal control (`desktop/src-tauri/src/worker.rs`).
- [x] 26. Windows WASAPI can deliver multichannel or >96 kHz audio, but transport accepts only 1–2 channels and 8–96 kHz; it currently fails mid-session. Normalize formats or reject them at capture setup with an actionable error (`desktop/src-tauri/src/platform/windows.rs`).
- [x] 27. Backend degraded/error events use `message`, while the frontend bridge reads only `error`; useful status becomes generic/undefined and protocol errors are dropped (`frontend/src/app/meetings/meetingBridge.ts`).
- [x] 28. Rate limiting trusts arbitrary `X-Forwarded-For`, allowing callers to rotate apparent IPs and bypass quotas. Forwarded headers are ignored because no trusted-proxy configuration exists (`backend/app/api/middleware/rate_limiting.py`).
- [x] 29. REST chat has an inference rate limit; the primary WebSocket message loop does not. Apply the configured LLM quota per authenticated account (`backend/app/api/routes/chat.py`).
- [x] 30. Upload route reads the full request before checking size. Reject by parsed size when available and read at most limit+1 bytes otherwise (`backend/app/api/routes/documents.py`).
- [x] 31. Web fetch buffered full responses before truncating. Stream and retain at most 500,000 response bytes (`backend/app/tools/web_tools.py`).
- [x] 32. Calculator allowed arbitrarily large exponentiation. Bound expression length, AST nodes, exponent, and integer result size (`backend/app/tools/calculator_tools.py`).
- [x] 33. Startup discovers/caches MCP tools and logs their count, but tool listings and agent bindings only expose built-ins. Wire discovered tools into the existing runtime tool access path (`backend/app/main.py`, routes/agent bindings).
- [x] 34. MCP JSON Schema conversion maps arrays/objects to `str`, so valid structured inputs fail local Pydantic validation before server invocation. Preserve supported JSON Schema types (`backend/app/mcp/client.py`).
- [x] 35. MCP `ClientSession.initialize()`/discovery has no timeout and is awaited during lifespan, so a stalled configured server can hang startup. Bound discovery while preserving existing graceful failure (`backend/app/mcp/client.py`, startup).
- [x] 36. `make setup` and `scripts/setup.sh` create root `.env`/data paths, then run backend commands whose relative config/data paths resolve under `backend/`; migrations can fail for a new checkout and setup can hide that failure. Align cwd/path handling (`Makefile`, script, backend settings).
- [x] 37. Conversation listing eagerly loads all message bodies to count messages/find the latest timestamp and has no pagination. Aggregate metadata in SQL without loading archive content (`backend/app/api/routes/chat.py`).
- [x] 38. Baseline full backend suite has 5 fixture failures: a standalone streaming app lacks `agent_registry`; four lifespan tests mock DB init but then query an uncreated `agent_configurations` table. Fix fixtures to model startup dependencies (`backend/tests/test_api/test_unified_streaming.py`, `backend/tests/test_app/test_main.py`).

### P3

- [x] 39. SQL settings example uses `sqlite:///`, but backend creates async engines; use `sqlite+aiosqlite:///` (`frontend/src/app/settings/page.tsx`).
- [x] 40. The static `default` select item duplicates the `default` entry once schema loading populates registered connections (`frontend/src/app/sql/page.tsx`).
- [x] 41. Deleting a selected legacy RAG collection removes the option but keeps the stale selected name, leaving Search enabled against a removed name (`frontend/src/app/rag/page.tsx`).
- [x] 42. UI labels Qdrant point count (chunks) as documents, inflating visible document totals (`frontend/src/app/rag/page.tsx`).
- [x] 43. Agent create sends untrimmed name but server normalizes its display name; selection lookup against the raw text fails for surrounding whitespace (`frontend/src/app/settings/page.tsx`).

## Progress log

- 2026-10-13: Confirmed starting repository, branch, clean tree, and HEAD. Read requested skills and test guidance; no glossary or ADR files were present. Created and pushed notes-only checkpoint `50c1128`.
- 2026-10-14: User approved all seven test seams. Implemented all P1 findings in red/green slices. Regressions first failed for unattached document reads, chat SQL database override, registering the app SQLite file under another driver, foreign RAG access, custom RAG profile lookup, and stopping after audio consumer failure. Focused combined verification: 84 tests passed across specialist agents, SQL/chat/meeting routes, meeting services/processors, RAG retrieval, and profile registry. Ruff on touched files reported only pre-existing diagnostics (unused/type-only imports, loop variable, and aliased TimeoutError); it reported no diagnostic on added implementation lines. P1 checkpoint `ed59637` was committed and pushed.
- 2026-10-14: Pushed P1 checkpoint `ed59637 fix: address high-priority review findings` to the existing feature branch.
- 2026-10-14: Implemented P2 findings 28–32 in red/green slices: ignore untrusted forwarded IPs, apply the configured LLM quota to each new authenticated WebSocket turn, cap upload reads at limit+1 after a parsed-size fast reject, stream web responses into a 500,000-byte buffer, and bound calculator expression/AST/exponent/integer-result size. The web-fetch test was updated to assert that iteration stops after the first over-limit chunk; the calculator test first failed on a safe-to-evaluate excessive exponent. Focused combined verification: `cd backend && .venv/bin/pytest tests/test_api/test_rate_limiting.py tests/test_api/test_chat_routes.py::TestWebSocketStream::test_websocket_chat_enforces_the_configured_inference_quota tests/test_api/test_documents_routes.py::TestDocumentUpload::test_rejects_oversized_upload_before_reading_file tests/test_tools/test_web_tools.py tests/test_tools/test_calculator_tools.py -q` — 86 passed. No proxy trust setting exists, so `X-Forwarded-For` is ignored on all routes until such a setting is added. This checkpoint is staged for commit/push.
- 2026-10-14: Implemented findings 07–23 and 37 in red/green slices. This includes saved prompt flow through SQL and Auto-RAG, write persistence and SQLite interruption/foreign-key behavior, owner-scoped legacy vector cleanup, actual image OCR and DOCX table text, independent memory controls and PATCH semantics, upload-aware chat submit, document question answers, stale response guards, conversation activity timestamps, UTC serialization, plus SQL-aggregated paginated conversation history with server-side search and a “Load older conversations” control. Focused backend verification: 233 passed across chat, SQL, documents, memory, RAG context, parser, and database tests. Focused frontend verification: 112 passed across Settings, SQL schema, RAG containers, chat, document viewer, and API tests; `tsc --noEmit` passed. Existing React `act(...)` and mocked `asChild` warnings remain. A test also verifies conversation summaries do not populate message bodies. Next checkpoint: commit and push this slice, then handle findings 24–27 and 33–36 before the final test fixture and UI findings.
- 2026-10-14: Implemented findings 24–27: transcription consumers now receive per-source PCM offsets, desktop Stop deactivates capture and drains queued/in-flight audio before terminal control (with an explicit timeout warning), Windows capture rejects unsupported formats at setup, and the meeting bridge accepts backend `message` status text. Targeted meeting, bridge, and Rust tests passed. Windows-specific code was reviewed but could not be cross-compiled from this macOS environment.
- 2026-10-14: Implemented findings 33–36 and 38: discovered MCP tools are listed and available to authenticated tool execution and agent nodes; nested JSON Schema arrays/objects preserve their types; discovery is bounded to five seconds and closes failed connections; setup/migration commands consistently use root-relative app configuration while Alembic resolves its script paths from its ini file; lifecycle fixtures now include their startup dependencies. Root-cwd backend import, shell syntax, Make dry-runs, and an in-memory migration to head succeeded.
- 2026-10-14: Implemented findings 39–43: corrected the async SQLite example, removed the duplicate SQL `default` option, cleared RAG selection/results after deleting the selected collection, labeled vector counts as chunks, and trimmed custom-agent names before create/selection matching. Regression tests first failed for the four P3 defects and then passed.
- 2026-10-14: Full verification after all changes: backend `pytest -q` — 830 passed; frontend Vitest — 351 passed; frontend `tsc --noEmit` passed; desktop `cargo test --lib` — 22 passed (local socket tests required loopback permission). `git diff --check` passed. Ruff still reports existing diagnostics in touched files (import order, older exception/style patterns); no broad cleanup was included. The Qdrant client emitted its usual unavailable-version warning during mocked tests. All 43 checklist findings are marked resolved. Windows platform code remains the only platform-specific compile/test gap.
- 2026-10-14: Closed the four coverage gaps found by the audit. Final-window and explicit failure cleanup now settles processor state; SQLite deadlines interrupt a running aiosqlite driver query before task cleanup; RAG mutation callbacks ignore stale container selections and errors; and audio offsets persist across reconnects until terminal meeting cleanup. Focused verification: backend meeting processor, meeting phase 2, and SQL tests — 70 passed; frontend ContainerManager tests — 5 passed; frontend `tsc --noEmit` and ESLint on touched RAG files passed. A real recursive SQLite timeout regression completed in under one second.

## Coverage audit — 2026-10-14

Reviewed implementation commit `91455d2` against `fb69f24` using `git diff fb69f24...HEAD`, with independent Standards and Spec reviews. The prior statement that all 43 findings were resolved was too strong. Code inspection and focused reproductions show 39 resolved, three partial (06, 21, 24), and one unresolved (11). No implementation fixes were made during this audit.

### Gaps identified during the audit

- **06, partial:** `MeetingAudioProcessor.stop()` calls `_flush_all()` before terminal cleanup, without a failure-safe cleanup path (`meeting_processor.py:199-205`). A consumer failing on a final partial window left the session active, the worker running, and another source's 16-byte buffer retained. Calling `fail()` then left the same bytes retained (`:218-227`). The existing regression covers only failure inside the full-window worker loop.
- **11, unresolved:** SQLite interruption runs only after `session.execute()` cancellation has completed (`sql_tools.py:189-205`). A real in-memory aiosqlite recursive aggregate over 10,000,000 rows, with a 0.01-second deadline, returned after 1.377 seconds and logged `sqlite_query_interrupt_failed`. The regression mocks `AsyncSession`, so it does not exercise driver cancellation. Interrupt the driver while execution is still running, then settle the query task/session.
- **21, partial:** `handleLoad`, retry, and removal capture the old container's `refreshFiles` callback. If selection changes A to B during the operation, the old callback starts an A refresh after B's refresh and takes the newest request ID (`ContainerManager.tsx:98-134`). A temporary rendered-component probe confirmed A's file list overwrites B; the probe was removed after the review. Guard the selected resource as well as request order.
- **24, partial:** `consumed_samples` belongs to a fresh `ProcessorSession` (`meeting_processor.py:71,105-113`), so reconnecting the same meeting resets source offsets. A public processor reproduction emitted offsets `[0, 1, 0]` across the initial and new sessions instead of `[0, 1, 2]`. Preserve a meeting's per-source audio timeline across stream sessions.

Resolved findings at audit time: **01–05, 07–10, 12–20, 22–23, 25–43**. Finding 25's timeout warning is surfaced by the normal frontend Stop command's returned `status.error`; the failed-phase-only event listener does not make that path silent. Finding 26's Windows-specific source remains uncompiled in this macOS environment. The four gaps above were subsequently fixed and covered by focused regressions.

### Standards review

- The same unrestricted MCP tool list is bound to every agent, despite `AGENTS.md` requiring domain-relevant tools. The attached-path guard covers built-in document tools only.
- New external-tool failure catches in chat/RAG do not log unexpected exceptions with tracebacks; widened document/SQL/web loops carry the same behavior.
- Added test functions/consumer closures omit signature annotations required by `AGENTS.md`.
- The SQLite interrupt failure handler logs neither the exception detail nor a traceback.
- The native Stop regression asserts timeout constants rather than delivery/ACK/terminal-control ordering or surfaced loss.
- Possible duplicated-code smell: tool lookup/invocation/error/recording loops now recur in chat, RAG, document, SQL, and web nodes. This is a judgment call, not a required broad refactor.

The audit itself changed documentation only. The follow-up implementation added behavioral regressions for all four gaps; the standards observations remain historical review context and were not expanded into a broad refactor for this request.
