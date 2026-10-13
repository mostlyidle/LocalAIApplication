# Action Item Planner and GitHub Agent implementation

Branch: `feature/action-item-planner-github-agent`

## Approved scope

Keep the existing LocalAIApplication chat and document parsing experience. Add an account-private action-item planner with review-before-save proposals, then a GitHub project agent using each user's own least-privilege connection. GitHub content is untrusted input; writes require explicit confirmation of the exact operation/content. Do not expose operator/global MCP tools as user-scoped tools.

## Milestones

- [x] 1. Account-owned action item CRUD and planner UI; verify account isolation and browser workflow.
- [x] 2. Source-grounded planner proposals from owned chat, meeting, and document records; accept/edit/ignore review flow; verify with mocked LLM and browser.
- [ ] 3. Per-account GitHub OAuth connection, encrypted credentials, repository selection, disconnect; verify OAuth and API behavior against a local fake GitHub service.
- [ ] 4. Read-only GitHub project agent for issues, pull requests/diffs, and checks, with safe links and task proposals; verify pagination, errors, ownership, and prompt-injection handling against fake GitHub.
- [ ] 5. User-confirmed GitHub issue/comment writes, end-to-end tests, docs and release review.

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
- Commit: pending.

## Resume instructions

Continue with milestone 3: per-account GitHub App user authorization, encrypted expiring credentials, repository selection, and disconnect. Preserve OAuth state/session binding and keep all repository access scoped to the user's authorized installation. After each completed milestone, update this file with changed files, commit SHA, exact checks and results, and the next action. Keep the account owner filter on every persistent record and GitHub request.

## Resume instructions

Start with milestone 1 on this branch. After each completed milestone, update this file with changed files, commit SHA, exact checks and results, and the next action. Keep the account owner filter on every persistent record and GitHub request.
