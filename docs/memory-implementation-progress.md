# Memory implementation progress

Use this file to resume the approved implementation without repeating completed work.

## Current position

- Plan: [memory implementation plan](memory-implementation-plan.md)
- Stage: 1 of 5, identity and ownership
- Branch: `feature/account-memory-stage1`
- Status: in progress; do not expose this checkpoint as a shared-account deployment yet
- Pushed checkpoints: `9ed6362` (account schema and legacy quarantine), `5863058` (operator-managed credentials), `221f466` (plan and resume notes), `14c6f91` (session endpoints), `c2caa64` (chat/document ownership and stable CSRF), `2bc4743` (meeting ownership), `5852d9d` (WebSocket revalidation), `f63bbbe` (agent API authentication), `1e9def0` (account-owned RAG collections), `cafa5c9` (account-owned named SQL connections), `c10f23d` (block unscoped direct file tools), `51b4ffd` (filesystem path containment), `a50af37` (account-owned agent workspaces), `30fc1ef` (dry-run legacy SQL record assignment), `09a6271` (safe explicit SQL/RAG legacy assignment), `e8181dd` (frontend and native meeting authentication), `560353f` (loopback-only Compose ports), `946260e` (remote proxy frontend configuration), `a6d4c50` (required meeting ownership)

## Completed checkpoint

- Added account and revocable-session database models. Session cookie tokens are stored only as digests; CSRF tokens are random and bound to their server-side session.
- Added an Alembic migration that creates a disabled `legacy-import-disabled` account and assigns existing conversations, documents, and meetings to it. Existing content is preserved and cannot be mistaken for a real user's data.
- Added non-null owner IDs to those three top-level data models. New rows temporarily default to the disabled legacy owner until authenticated route creation is wired in.
- Added a migration regression test that seeds all three record types, upgrades the database, and checks the disabled quarantine owner and preserved record IDs.
- Added Argon2 password hashing and an operator CLI for account creation and password resets. Password resets revoke active sessions. There is no public registration route.
- Added credential and reset/revocation tests.
- Verified with `pytest tests/test_services/test_accounts.py tests/test_services/test_account_identity_migration.py -q` (9 passed), Ruff lint, and Ruff format check.
- Added `/api/v1/auth/login`, `/auth/me`, and `/auth/logout` with random opaque cookie sessions, SHA-256 token digests, HttpOnly/SameSite cookies, configurable Secure cookies and expiry, session revocation, and a session-bound CSRF token required for mutations.
- Added REST session/CSRF and WebSocket origin/session dependencies, plus login, CSRF replay, logout, credential, and migration tests. Chat and meeting streams use the WebSocket dependency.
- Verified the auth slice with 12 focused tests, Ruff lint, and Ruff format check. Tests emit one existing Qdrant client-version warning because no Qdrant server is running.
- Enforced account ownership on chat and document REST routes. Conversation history, listing, continuation, deletion, uploaded-document analysis/read/delete, and chat attachments now require the owner ID from the authenticated session. Cross-account IDs return 404.
- Wired chat streaming to the authenticated WebSocket dependency, which checks the browser origin and resolves the session using a short-lived DB session.
- Added cross-account chat/document tests and updated API/WebSocket fixtures.
- `/auth/me` now performs a read-only refresh using the session's stable CSRF token. Migration `20261012_07` replaces stored CSRF digests with session-bound tokens and revokes existing sessions that require reauthentication. Added a migration test for this transition.
- Reverified the full account/chat/document/auth focused set with 87 passing tests, Ruff lint, and Ruff format check. One Qdrant client-version warning remains because no Qdrant server is running.
- Enforced account ownership on meeting creation, read, stop, delete, and audio WebSocket claim/start/audio/stop/failure paths. Added cross-account route and stream tests; 28 meeting/auth tests pass. The service module has three pre-existing Ruff UP041 suggestions; targeted checks ignoring that unrelated rule pass.
- Chat and meeting WebSockets now revalidate session expiry/revocation at least every 60 seconds, including idle streams. A revoked meeting session stops the meeting before the socket closes. Added integration tests for both stream types; the combined account/chat/document/meeting/migration set passes 112 tests. Ruff and formatting pass on changed files; the three existing meeting-service UP041 suggestions were excluded from lint.
- Added authenticated-session requirements to agent discovery, tasks, direct tool execution, SQL, and RAG endpoints (health checks remain public). Task asset lookup and RAG ingestion now require document ownership. The focused API checks pass 57 tests with Ruff and format checks clean (three unrelated existing Ruff rules excluded in legacy tool/health code).
- Added a RAG collection ownership registry. New application collections are reserved to the uploading account before vector writes; foreign and unregistered legacy collections are hidden and rejected. Validated collection names are bounded to Qdrant's 63-character limit. Dataloader-owned collections remain shared and read-only. These checks cover RAG search/list/delete/ingest, the direct RAG search tool, selected and automatic RAG agents, and task execution; direct RAG list/ingest tools now require the scoped API routes. A migration leaves pre-existing unregistered collections quarantined rather than assigning them to an account.
- Verified the combined account/chat/document/meeting/RAG/task/SQL/tool/migration set: 183 tests pass. Ruff passes with existing unrelated typing/style rules excluded; focused formatting checks pass on new/clean files. The Qdrant client warning remains because no Qdrant server is running.
- Added a SQL connection ownership registry. Named connections registered through the API are account-owned; foreign and pre-existing unregistered names are hidden/rejected by SQL APIs and direct SQL tools. The configured `default` database remains a shared application resource. Registered connection URLs remain process-local as before; after a backend restart, the owner must re-register the connection before querying it. The combined focused suite passes 185 tests.
- Blocked direct `/tools/execute` calls to document and filesystem tools because their file paths are not account-scoped. Safe direct tools and account-scoped document workflows remain available. Added route tests; all 16 tool-route tests pass. Ruff and formatting pass with the same unrelated legacy lint rules excluded, and `git diff --check` is clean.
- Fixed filesystem path containment to use resolved path ancestry rather than string prefixes, preventing sibling directories such as `data-private` from matching an allowed `data` root. Added a regression test; all 21 filesystem-tool tests pass. Focused Ruff/format checks pass with unrelated pre-existing lint findings excluded.
- Scoped software-review workspace access to the authenticated account directory under `AGENT_WORKSPACE_ROOT/<account-id>`. Missing assignments fail closed with 422. Added workspace helper, task-runner, and route coverage, and updated README operator instructions. The combined focused workspace/task set passes 23 tests.
- Added `account_admin assign-legacy`, which previews explicitly selected quarantined conversations/documents/meetings and RAG collections by default and requires `--apply` to transfer them. Missing and foreign-owned records are rejected; repeat assignment to the same account is safe. RAG imports verify the live collection exists, uses a supported schema, and is not Dataloader-owned. Added README CLI instructions and tests for dry-run/apply, foreign-owner rejection, and shared-loader rejection. The focused account-admin tests pass 12 cases.
- Added the frontend sign-in gate, account display, and sign-out. API calls include cookies, mutating requests send the in-memory CSRF token, uploads and meeting calls follow the same rule, and 204 logout responses are handled. Signed-out views do not mount the app shell or chat socket.
- Added a native meeting stream-ticket endpoint for Tauri: ticket hashes are stored server-side, each ticket is tied to its meeting and parent login session, and socket revalidation checks that session by ID. Tauri requests the ticket through the authenticated UI before opening its WebSocket; a handshake test verifies the ticket header. The migration test verifies the new ticket table.
- Verified frontend: 297 tests pass, TypeScript passes, and targeted ESLint has no errors. Verified Rust transport: `cargo fmt --check` and 19 Rust tests pass. Verified focused backend meeting/auth/migration suite: 17 tests pass. Qdrant emits its existing compatibility warning because no server is running; Rust emits existing native deprecation/dead-code warnings.
- Bound Ollama, ChromaDB, Qdrant, backend, and frontend Compose host ports to `127.0.0.1`; internal Compose service networking is unchanged. README states local-only defaults and the TLS/API/WebSocket configuration needed for remote use.
- Made frontend API, WebSocket, and server-side backend URLs build-configurable. Same-origin browser mode now derives `ws://` or `wss://` from the page origin; README documents HTTP API rewrite versus direct WebSocket proxying and the origin/cookie settings. `docker compose config --quiet`, the production frontend Docker build, and the focused same-origin constants test (8 tests) pass.
- Required `owner_id` when the meeting service creates a meeting; its only application route already passes the authenticated account. Service tests now identify their legacy fixture owner explicitly; focused meeting lifecycle tests pass (18 tests).
- Documented and narrowed built-in MCP usage to operator-only local stdio. SQL, document, and RAG MCP functions are not account-scoped, so they must not be exposed to shared users or over HTTP. `mcp_servers.json` remains trusted operator configuration and is executed at backend startup; discovered tools are not currently wired into agent execution.
- Removed the legacy-owner ORM defaults from conversations, documents, and meetings after auditing application constructors; each route/service now passes an owner explicitly. Legacy test records specify the quarantine owner. Added DB tests proving missing owners are rejected. The affected API/service set passes 146 tests; Ruff lint passes with documented legacy exclusions. Ruff format still reports pre-existing drift in several touched test modules, which was not swept into this change.
- The first `uv run` attempt could not reach PyPI to build the project environment. Reused the repository's existing `.venv` directly for the successful checks.
- The implementation time estimate in the plan is explicitly non-binding and does not limit the scope or completion criteria.

## Not implemented yet

- MCP servers remain inherently outside the HTTP account session boundary. The supported boundary is operator-only local stdio; no authenticated remote MCP adapter is implemented.
- Remote shared-deployment boundary: frontend can now be built for same-origin HTTPS/WSS proxying, but deployment still needs an operator-supplied hostname, TLS reverse proxy, and matching CORS/WebSocket origin configuration. No real remote hostname is available to verify.

## Resume here

1. Complete the MCP isolation decision: keep tools operator-only, remove or defer startup of configured external MCP commands if they are not needed, or add an authenticated adapter before account access. The API's configured `default` SQL connection remains explicitly shared; custom connections are private.
2. Run the full Stage 1 account-isolation matrix after MCP scope is settled, including REST, WebSockets, direct tools, resources, RAG, SQL, and meetings.
3. For an actual shared deployment, configure the operator's hostname, TLS reverse proxy, and matching CORS/WebSocket origins; frontend same-origin URL support and native meeting ticket auth are implemented.

Do not run built-in MCP servers through HTTP or expose them to shared users. Direct MCP invocation remains a trusted local-operator capability until an authenticated adapter propagates account identity and enforces each tool's resource ownership.

## Important safety decision

The legacy owner is disabled and has no login credential. Never auto-assign its records to the first account created. Keep account-level sharing disabled until all direct API, WebSocket, tool, MCP, and resource access paths enforce ownership.
