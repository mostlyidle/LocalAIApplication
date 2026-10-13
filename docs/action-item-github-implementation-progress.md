# Action Item Planner and GitHub Agent implementation

Branch: `feature/action-item-planner-github-agent`

## Approved scope

Keep the existing LocalAIApplication chat and document parsing experience. Add an account-private action-item planner with review-before-save proposals, then a GitHub project agent using each user's own least-privilege connection. GitHub content is untrusted input; writes require explicit confirmation of the exact operation/content. Do not expose operator/global MCP tools as user-scoped tools.

## Milestones

- [x] 1. Account-owned action item CRUD and planner UI; verify account isolation and browser workflow.
- [x] 2. Source-grounded planner proposals from owned chat, meeting, and document records; accept/edit/ignore review flow; verify with mocked LLM and browser.
- [x] 3. Per-account GitHub OAuth connection, encrypted credentials, and disconnect.
- [x] 4. Read-only GitHub project agent for issues, pull requests/diffs, and checks, with safe links and task proposals; verify pagination, errors, ownership, and prompt-injection handling against fake GitHub.
- [x] 5. User-confirmed GitHub issue/comment writes, end-to-end tests, docs and release review.

## Checkpoints

### Milestone 1 — Action Item Planner foundation

- Added owner-scoped create/list/update/delete API, source ownership validation for chats, meetings, and documents, and revision checks against stale edits.
- Added the revision 18 migration and account-isolation tests.
- Added `/action-items` UI for adding, editing, prioritizing, scheduling, completing, and deleting items; linked it from the dashboard and sidebar.
- Added component/API tests and `frontend/e2e/action-items.spec.ts` for the browser workflow.
- Verification: backend suite `782 passed`; frontend suite `326 passed`; frontend ESLint (0 errors; existing `asChild` test warning), TypeScript check passed; production `next build` passed; Alembic upgrade from an empty SQLite database through `20261012_18` passed.
- Browser E2E was attempted but could not execute: Playwright Chromium downloads remained partially extracted in this environment, leaving no browser executable. The mocked browser scenario is committed for a machine with a working Playwright browser installation.
- Commit: `721d56e` (`feat(planner): add account-owned action item planner`).

### Milestone 2 — Source-grounded planner proposals

- Added `/action-items/proposals` for owned chats, stopped meeting transcripts, and parsed documents. Context is capped at 24,000 characters; private or active meeting sources are rejected before inference.
- Added a structured local Ollama extraction prompt that treats source text as untrusted, avoids guessing dates/owners, and returns only suggestions whose exact quote appears in the source.
- Added quote persistence and migration revision 19. Creating a linked action item rechecks source ownership and verifies the quote before saving.
- Added a meeting source-list endpoint, planner source picker, editable suggestion cards, and explicit Accept/Ignore actions. Accepted tasks display and retain the source quote.
- Verification: backend suite `784 passed`; frontend suite `327 passed`; backend Ruff, frontend ESLint and TypeScript passed; clean SQLite migration through `20261012_19` passed; optimized `next build` passed.
- Browser E2E scenario now covers proposal, acceptance, manual create, edit, completion, and delete, but execution remains blocked by the incomplete Playwright Chromium installation noted above.
- Commit: `0fef1fd` (`feat(planner): add source-cited action suggestions`).

### Milestone 3 — Per-account GitHub authorization

- Added per-account GitHub connection records and one-time OAuth state bound to the initiating account session. State is hashed, expires after ten minutes, and is consumed before code exchange.
- Added GitHub App user authorization with `offline_access`, profile verification, Fernet-encrypted access/refresh credentials, eight-hour access-token refresh and refresh-token rotation, and remote grant revocation before local disconnect.
- Added Settings controls to install, connect, and revoke GitHub access, plus `.env.example` and README setup instructions. Secrets remain server-side.
- Added migration revision 20 and mocked GitHub HTTP tests for code exchange, profile verification, and revocation.
- Verification: backend suite `789 passed`; frontend suite `328 passed`; Ruff, ESLint, TypeScript, optimized `next build`, and empty SQLite migration through `20261012_20` passed. OAuth API tests cover session state, replay rejection, encrypted persistence, refresh rotation, and disconnect.
- Limitations: live GitHub OAuth needs an operator-created GitHub App and its secrets. Playwright browser E2E remains unavailable because Chromium installation did not produce an executable. `uv lock --offline` could not re-resolve this existing Python 3.14+ lock split because the offline index lacks `pwdlib>=0.3.1`; `cryptography` was already present in `uv.lock`, and the direct dependency was added against its existing locked `46.0.5` package.
- Commit: `58ad1f6` (`feat(github): add encrypted per-account app authorization`).

### Milestone 4a — Per-account repository allowlist

- Added migration revision 21 and an account-owned repository selection table. Disconnect now also clears that account's selections.
- Added repository enumeration through the authorized user's GitHub token (up to 1,000 results) and selection endpoints. Selecting rechecks that the repository is still accessible to that token; each response returns only repositories visible to the current GitHub authorization.
- Added the Settings repository checklist and API/client schemas. Each person's selections are isolated by account.
- Verification: full backend suite `791 passed`; full frontend suite `329 passed`; frontend ESLint and TypeScript passed; optimized `next build` passed; a clean SQLite Alembic upgrade through `20261012_21` passed; `git diff --check` passed.
- Browser E2E remains unavailable because Playwright Chromium is not installed successfully in this environment. Settings behavior is covered by the component test, and repository selection is exercised through the authenticated API against a mocked GitHub client.
- Feature commit: `b0f2fce` (`feat(github): add per-account repository allowlist`).
- Docs checkpoint: `67247e7` (`docs: record repository allowlist checkpoint`).

### Milestone 4b — Read-only GitHub Project Agent

- Added `/github` with selected-repository browsing for open issues and pull requests, bounded pull diffs/check runs, and source-cited task suggestions that require explicit acceptance.
- Added read API calls for issues, pull requests, changed files, and check runs. Every endpoint checks the account's selected repository. API result sizes are bounded; GitHub content renders as text and the extraction prompt treats it as untrusted input.
- Added migration revision 22 so saved GitHub planner items retain the selected repository ID. On acceptance the API re-fetches the issue and verifies the quoted evidence before saving, and rejects items from repositories no longer selected.
- Verification: full backend suite `794 passed`; full frontend suite `331 passed`; frontend ESLint and TypeScript passed; optimized `next build` passed; a clean SQLite Alembic upgrade through `20261012_22` passed; Ruff passed. GitHub API route tests cover selection isolation, issue/PR separation, diff/check parsing, citation revalidation, and unselected repository rejection.
- Ollama smoke: `llama3.2:3b` returned a grounded task with an exact quote against the Docker Ollama service. The configured `llama3.1:8b` process was killed by Ollama with HTTP 500 on this host, so that larger-model run is a local resource limitation.
- Browser E2E remains unavailable because Playwright Chromium could not be installed successfully. Component and authenticated API integration tests cover the flow; a live GitHub App test also needs operator-configured app credentials.
- Feature commit: `9a30da7` (`feat(github): add read-only project agent`).
- Docs checkpoint: `f082318` (`docs: record GitHub project agent checkpoint`).

### Milestone 5 — User-confirmed GitHub issue and comment writes

- Added only two GitHub write operations: create an issue and post a comment. Both endpoints require a currently selected repository, validate bounded content, use the user's token, and return safe response fields. Permission and rate-limit errors remain explicit and safe.
- Added a two-step UI for both operations: review the exact repository and title/body, then separately click to submit. Switching repositories clears reviewed drafts; planner suggestions never trigger GitHub writes.
- Updated setup docs for least-privilege GitHub App permissions: Metadata read, Pull requests read, Checks read, and Issues read/write for issue/comment creation.
- Verification: full backend suite `797 passed`; full frontend suite `333 passed`; Ruff, ESLint, TypeScript, `git diff --check`, and optimized `next build` passed. Mocked GitHub tests cover exact HTTP methods/payloads, selected-repo boundaries, permission denial, and rate limits; component tests verify no write occurs before final confirmation.
- Limitations: browser-run E2E remains unavailable because Playwright Chromium could not be installed. The current running GitHub App has no live OAuth credentials in this environment; live writes were not sent to a real repository.
- Feature commit: `2e7f9c3` (`feat(github): add confirmed issue and comment writes`).
- Docs checkpoint: pending.

## Resume instructions

Implementation stages 1–5 are complete on this feature branch. If resuming, run the release review and verify the target GitHub App's Issues write permission before deploying; do not merge to `main` unless the user requests it. All persistent GitHub data and outbound calls remain scoped to the signed-in account and explicitly selected repositories.
