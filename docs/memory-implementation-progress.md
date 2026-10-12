# Memory implementation progress

Use this file to resume the approved implementation without repeating completed work.

## Current position

- Plan: [memory implementation plan](memory-implementation-plan.md)
- Stage: 1 of 5, identity and ownership
- Branch: `feature/account-memory-stage1`
- Status: in progress; do not expose this checkpoint as a shared-account deployment yet
- Pushed checkpoints: `9ed6362` (account schema and legacy quarantine), `5863058` (operator-managed credentials)

## Completed checkpoint

- Added account and revocable-session database models. Sessions store only a token digest.
- Added an Alembic migration that creates a disabled `legacy-import-disabled` account and assigns existing conversations, documents, and meetings to it. Existing content is preserved and cannot be mistaken for a real user's data.
- Added non-null owner IDs to those three top-level data models. New rows temporarily default to the disabled legacy owner until authenticated route creation is wired in.
- Added a migration regression test that seeds all three record types, upgrades the database, and checks the disabled quarantine owner and preserved record IDs.
- Added Argon2 password hashing and an operator CLI for account creation and password resets. Password resets revoke active sessions. There is no public registration route.
- Added credential and reset/revocation tests.
- Verified with `pytest tests/test_services/test_accounts.py tests/test_services/test_account_identity_migration.py -q` (9 passed), Ruff lint, and Ruff format check.
- The first `uv run` attempt could not reach PyPI to build the project environment. Reused the repository's existing `.venv` directly for the successful checks.
- The implementation time estimate in the plan is explicitly non-binding and does not limit the scope or completion criteria.

## Not implemented yet

- Login/logout/current-account API, secure cookies, CSRF checks, and session validation for REST/WebSocket.
- Ownership filters and authorization for chat, uploaded file access, meetings, RAG collections, SQL connections, workspace roots, tools, and MCP.
- Dry-run and explicit legacy data assignment/import command.
- Frontend sign-in and shared-deployment network boundary.

## Resume here

1. Add login/logout/current-account endpoints, hashed opaque sessions, secure cookies, CSRF checks, and focused security tests.
2. Enforce account ownership for each resource family and every WebSocket/tool entry point before enabling shared-account access.
3. Add dry-run and explicit assignment for quarantined legacy records.
4. Replace the temporary legacy-owner defaults after every creation path supplies the authenticated account.

## Important safety decision

The legacy owner is disabled and has no login credential. Never auto-assign its records to the first account created. Keep account-level sharing disabled until all direct API, WebSocket, tool, MCP, and resource access paths enforce ownership.
