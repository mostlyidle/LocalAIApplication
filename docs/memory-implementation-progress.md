# Memory implementation progress

Use this file to resume the approved implementation without repeating completed work.

## Current position

- Plan: [memory implementation plan](memory-implementation-plan.md)
- Stage: 1 of 5, identity and ownership
- Branch: `feature/account-memory-stage1`
- Status: in progress; do not expose this checkpoint as a shared-account deployment yet
- Pushed checkpoints: `9ed6362` (account schema and legacy quarantine), `5863058` (operator-managed credentials), `221f466` (plan and resume notes), `14c6f91` (session endpoints)

## Completed checkpoint

- Added account and revocable-session database models. Sessions store only a token digest.
- Added an Alembic migration that creates a disabled `legacy-import-disabled` account and assigns existing conversations, documents, and meetings to it. Existing content is preserved and cannot be mistaken for a real user's data.
- Added non-null owner IDs to those three top-level data models. New rows temporarily default to the disabled legacy owner until authenticated route creation is wired in.
- Added a migration regression test that seeds all three record types, upgrades the database, and checks the disabled quarantine owner and preserved record IDs.
- Added Argon2 password hashing and an operator CLI for account creation and password resets. Password resets revoke active sessions. There is no public registration route.
- Added credential and reset/revocation tests.
- Verified with `pytest tests/test_services/test_accounts.py tests/test_services/test_account_identity_migration.py -q` (9 passed), Ruff lint, and Ruff format check.
- Added `/api/v1/auth/login`, `/auth/me`, and `/auth/logout` with random opaque cookie sessions, SHA-256 token digests, HttpOnly/SameSite cookies, configurable Secure cookies and expiry, session revocation, and a session-bound CSRF token required for mutations.
- Added REST session/CSRF and WebSocket origin/session dependencies, plus login, CSRF replay, logout, credential, and migration tests. Chat streaming now uses the WebSocket dependency; meeting streaming remains pending.
- Verified the auth slice with 12 focused tests, Ruff lint, and Ruff format check. Tests emit one existing Qdrant client-version warning because no Qdrant server is running.
- Enforced account ownership on chat and document REST routes. Conversation history, listing, continuation, deletion, uploaded-document analysis/read/delete, and chat attachments now require the owner ID from the authenticated session. Cross-account IDs return 404.
- Wired chat streaming to the authenticated WebSocket dependency, which checks the browser origin and resolves the session using a short-lived DB session. Session revocation is checked when opening the stream; periodic revalidation during a long-running connection remains to be added.
- Added cross-account chat/document tests and updated API/WebSocket fixtures.
- `/auth/me` now performs a read-only refresh using the session's stable CSRF token. Migration `20261012_07` replaces stored CSRF digests with session-bound tokens and revokes existing sessions that require reauthentication. Added a migration test for this transition.
- Reverified the full account/chat/document/auth focused set with 87 passing tests, Ruff lint, and Ruff format check. One Qdrant client-version warning remains because no Qdrant server is running.
- The first `uv run` attempt could not reach PyPI to build the project environment. Reused the repository's existing `.venv` directly for the successful checks.
- The implementation time estimate in the plan is explicitly non-binding and does not limit the scope or completion criteria.

## Not implemented yet

- Ownership filters and authorization for meetings, RAG collections, SQL connections, workspace roots, direct tools/tasks, agents, and MCP.
- Dry-run and explicit legacy data assignment/import command.
- Frontend sign-in and shared-deployment network boundary.

## Resume here

1. Add periodic session revocation/expiry checks to long-lived chat and meeting streams; enforce meeting ownership at create/read/stop/delete and WebSocket paths.
2. Enforce ownership for RAG collections, SQL connections, workspace roots, direct tools/tasks, agents, and MCP; review every direct access surface.
3. Add dry-run and explicit assignment for quarantined legacy records.
4. Add frontend sign-in and the shared-deployment network boundary.
5. Replace the temporary legacy-owner defaults after every creation path supplies the authenticated account.

## Important safety decision

The legacy owner is disabled and has no login credential. Never auto-assign its records to the first account created. Keep account-level sharing disabled until all direct API, WebSocket, tool, MCP, and resource access paths enforce ownership.
