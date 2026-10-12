# Persistent memory implementation plan

Status: implementation and Stage 5 local verification complete. External-provider and remote-deployment checks remain environment-dependent.

Deployment decision: separate sign-in accounts for a shared application, confirmed by the user. Memory remains on the deployment host; it is private to the signed-in account, not automatically shared between people.

## 1. Current behavior and the gap

The application already persists conversation messages in its application database. REST and WebSocket chat reload prior messages when the same `conversation_id` is supplied. Selected specialist profiles receive recent conversation context; RAG has its own bounded history handling. This is conversation continuity, not durable recall across conversations.

The gaps observed in the checkout are:

- `Conversation`, `Document`, and `Meeting` have no account ownership field. There is no sign-in/account dependency protecting their routes.
- `useChat` holds its active conversation ID in component state. It exposes `loadConversation`, but the current chat UI does not connect it to a saved-conversation browser or automatic resume flow.
- New conversations do not retrieve relevant information from previous conversations.
- General chat loads all stored messages; selected task profiles use a recent-message window. Context handling is inconsistent and can grow beyond a model's useful budget.
- Direct `/tasks` calls have no conversation input or persistent personal memory context.

Relevant existing integration points:

| Area | Existing source |
|---|---|
| Persisted messages and future ownership | `backend/app/models/db_models.py`, `backend/alembic/versions/` |
| REST/streaming chat and history | `backend/app/api/routes/chat.py` |
| Graph context and routing | `backend/app/agents/state.py`, `backend/app/agents/orchestrator.py`, specialist agent nodes |
| Profile task execution | `backend/app/services/task_runner.py`, `backend/app/api/routes/tasks.py` |
| RAG evidence budgeting | `backend/app/services/rag_context.py`, `backend/app/services/hybrid_vector_store.py` |
| Chat persistence UI | `frontend/src/hooks/useChat.ts`, `frontend/src/components/chat/ChatWindow.tsx`, `frontend/src/components/shared/AppSidebar.tsx` |

## 2. Recommended scope

Implement three complementary forms of memory:

| Memory | What it contains | When it is used |
|---|---|---|
| Conversation context | Recent turns plus a bounded summary of older turns | Continuing the same conversation |
| Saved memories | User-approved preferences, stable personal facts, and project decisions | Relevant requests in any conversation belonging to that account |
| Past-chat recall | Source-linked summaries of earlier conversations | Questions referring to previously discussed topics |

For example, an account can save “Use Python examples and concise explanations.” In a new conversation, a coding agent can apply that preference. A later question such as “What did we decide about the invoice parser?” can retrieve the account's earlier discussion summary and link back to the original conversation.

Keep SQLite/SQLAlchemy as the authoritative record. Use a separate Qdrant memory collection as a derived semantic-search index. Reuse Ollama and the existing embedding configuration; no separate memory model, cloud memory provider, Redis, or new database server is required for the first release.

LangGraph distinguishes thread-level persistence from long-term information shared across sessions. A checkpointer alone would not supply account identity, user controls, or cross-conversation recall. Keep the existing database-backed transcript persistence rather than introducing a second competing transcript store. [LangGraph memory documentation](https://docs.langchain.com/oss/python/langgraph/add-memory).

## 3. Account identity and data isolation

This is the first implementation gate. A client-provided `user_id` or a name mentioned in chat is not proof of identity.

### Sign-in design

Use locally hosted accounts with passwords and opaque server-side sessions:

- Store password hashes with an established Argon2 implementation, such as `pwdlib[argon2]`, pinned in the lockfile. This is a justified security dependency; do not implement password hashing manually. [FastAPI password-hashing guidance](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/).
- Store only a hash of a cryptographically random session token. Browser sessions use an HttpOnly cookie, expiry, revocation on logout, and Secure cookies when served over HTTPS.
- Enforce CSRF protection for cookie-authenticated mutations and validate WebSocket origins and sessions. Recheck revoked/expired sessions on long-lived streams and terminate affected connections.
- Create accounts and reset passwords through an operator CLI initially, with password input hidden and session revocation on reset. Avoid adding email delivery or open registration to the memory feature.
- Derive the principal in a shared FastAPI dependency and the equivalent WebSocket boundary. Never trust ownership fields submitted in JSON.

Cookie attributes, expiration, and revocation are part of session protection; the application-specific choice here is a server-side session rather than adding JWT refresh-token infrastructure. [OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).

### Ownership must reach tools as well as routes

Account scoping must cover conversation lists, history, deletion, uploads, asset resolution, memories, and meetings. The same principal must reach graph tools, direct tool execution, and specialist task calls.

RAG collection names and SQL connection names currently refer to deployment resources. Add an ownership/access registry rather than treating knowledge of a name as permission. Every dense, BM25, rewrite, source-fetch, and deletion path must apply authorization. Workspace roots must be assigned or granted by the operator; a remembered path must never grant filesystem access.

Keep operator-only MCP servers and administrative diagnostics outside the shared-user interface unless they have an authenticated, authorized adapter. Audit external MCP tools before allowing them to receive user context. Updating the web API alone does not secure a separate unauthenticated tool surface.

Do not expose Qdrant, ChromaDB, Ollama, or sensitive readiness details directly to shared users. Bind infrastructure ports to loopback or an internal Compose network, with only the authenticated application exposed through HTTPS for network use.

The native desktop meeting client must acquire an authorized session before protected meeting requests. Its consent checks remain mandatory. If that client is not adapted in the first milestone, do not enable its unauthenticated endpoints on the shared deployment.

### Existing data migration

Existing chats do not identify their human owner. Do not assign all historical data to the first person who signs in.

Create a disabled legacy-import owner and quarantine existing conversations, documents, meetings, and collection registrations under it. Provide an operator dry-run/import command to assign explicitly selected records to the correct account. Preserve old records and vector collections until the migration has been reviewed. New user-owned collections must preserve the recorded embedding identity; reindex into a new collection when ownership/schema changes require it.

Past conversations become eligible for memory extraction only after ownership is established and that account opts into past-chat recall.

## 4. Proposed storage

Use Alembic migrations and the existing application database. Exact column names can follow local style during implementation.

| Record | Proposed fields and behavior |
|---|---|
| Account | ID, unique login, display name, password hash, enabled flag, memory settings/epoch, timestamps |
| Session | Token hash, account ID, creation/expiry/revocation timestamps |
| Conversation | Existing fields plus owner ID, cross-chat-recall setting, summary, summary coverage marker, revision |
| Message | Existing fields plus stable sequence/turn ID and a recall-exclusion marker; ownership follows the conversation |
| Memory | ID, owner ID, kind, text, optional user-selected project scope, source conversation/message IDs, origin agent, approval status, timestamps, expiry, revision, deletion marker |
| Memory job | Operation, owner/source IDs, source revision, idempotency key, status, attempts, lease/retry timestamps, sanitized failure code |

Saved preferences and facts are small SQL records. Conversation summaries live with their conversation; only eligible summaries and approved memories are indexed in Qdrant. Every recalled statement remains traceable to its source or to an explicit manual user entry.

An optional project label groups an account's memories; it is not a filesystem or collection permission. Do not build team-sharing/project-permission infrastructure in this feature.

Add stable message ordering and client-turn idempotency where needed so reconnects cannot save the same turn or extraction job twice. Summary coverage should track an ordered message boundary, not only a timestamp. Revisions prevent a delayed worker from overwriting a newer edit or recreating a deleted memory.

## 5. Memory creation, correction, and deletion

### User controls

Give each account two independent settings:

- Use saved memories across conversations.
- Use summaries of previous chats for recall.

Both are off until the account opts in. Add a per-conversation “Exclude this chat from memory” control. Explain that this excludes cross-chat recall and extraction; it does not delete the ordinary chat transcript.

Provide a Memory page with search, source links, edit, delete, and delete-all controls. Add “Remember this” on a user message, showing the exact proposed fact before saving it. Extracted suggestions require approval; assistant-generated guesses do not become personal facts automatically.

### Write rules

Store stable, relevant facts and preferences. Do not automatically retain credentials, secret keys, full uploaded files, tool output, transient market prices, or sensitive medical/financial details. Sensitive facts can only be saved through an explicit reviewed user action.

An approved correction replaces or supersedes the prior value. Do not retain contradictory active preferences or infer that the latest assistant answer is authoritative. Unclear conflicts produce a review suggestion rather than silent replacement.

Conversation compaction can summarize any owned saved chat for continuity within that chat. Cross-chat indexing and extraction require the account's separate opt-in and an eligible source conversation. A summary records the topic, decisions, unresolved questions, and user-stated context, with source coverage. Summaries are derived and may be incomplete; exact facts must be verified from owned source messages when needed. Validate structured extraction output and screen secret-like content; pattern detection alone cannot guarantee detection of every sensitive fact.

### Forgetting

Delete makes a memory immediately ineligible in SQL, then queues vector cleanup. Search results are revalidated against SQL so delayed index cleanup cannot make deleted content reappear. Deleting a conversation also invalidates its summaries and automatically derived memories; provide a separate reviewed option to retain an explicitly saved fact as a manual entry.

For source-derived memories, retain a content-free suppression marker for the deleted record/source turn and invalidate covering recall summaries. Exclude suppressed source turns from regenerated recall summaries and on-demand recall. Offer removal of related duplicates so deleting one record is not presented as forgetting every independent occurrence of a fact.

Delete-all also invalidates recall summaries, queued extraction/index jobs, and any derived cache entries. Advance an account memory epoch and disable past-chat recall until the user enables it again; re-enabling must not automatically reindex excluded earlier sources. Editing or deleting a source must invalidate its derived content. Backups can still contain earlier data; document the backup retention policy rather than claiming deletion rewrites old backups.

## 6. Reading memory and controlling context

Add one shared `MemoryService` and a typed `MemoryContext` used by REST chat, streaming chat, the orchestrator, and the task runner. Pass memory separately from the user's current prompt. Replace the current task-history string concatenation with structured context during this integration.

The turn sequence is:

1. Authenticate the account and authorize the requested conversation/assets/resources.
2. Load recent turns and the valid summary for that conversation.
3. Read applicable approved facts and retrieve a small set of account-owned past-chat summaries.
4. Build the agent prompt within its selected context/output budget; generate and persist the answer.
5. Commit any eligible summary/index jobs with the durable turn; process them asynchronously.

Memory is contextual data, not an instruction authority. Current explicit requests override saved preferences. Retrieved text cannot change tool permissions, execute workflows, select an unauthorized database, or direct the system to ignore its instructions. Delimit and label memory separately from system instructions and retrieved document evidence.

Reserve space for system text, current input, tool schemas, image inputs, and answer output before admitting memory. Trim older turns first while retaining a summary, and avoid including a turn twice through both a summary and raw history. Use a conservative supported budget calculation initially; multimodal costs need their own allowance. Test small context windows as well as larger ones.

For RAG, retrieved authorized document passages remain the evidence for factual answers and citations. Personal preferences may shape presentation or help resolve an explicit follow-up, but personal memory must not be cited as a document passage. Do not silently change the selected collection or replace the current retrieval question with an unrelated remembered fact.

## 7. Behavior by agent

| Agent | Useful memory | Boundary |
|---|---|---|
| `chat` | Preferences, approved personal facts, earlier discussions | Current request wins over old preferences |
| `document_analytics` | Preferred extraction fields and output format | Document content remains the factual source |
| `image_analysis` | Description preferences and relevant discussion context | Describe the current image; do not treat an old image as current evidence |
| `image_fraud` | Prior discussion in the UI | Deterministic forensic signals remain derived only from the supplied image |
| `image_generation` | Preferred styles | A current explicitly supplied/selected ComfyUI workflow is still required |
| `rag` | Preferences and relevant conversation context | Authorized retrieved passages support the answer |
| `rag_v2` | Same account memory as `rag` | Retain stricter passage-grounding and citation requirements |
| `software_engineer` | Language preferences and approved project decisions | Read the current authorized workspace and verify assumptions |
| `sql` | Preferred output and approved metric definitions | Check live schema; preserve database authorization and read-only defaults |
| `stock_research` | Explicitly saved goals and presentation preferences | Fetch current market data; old prices are not current facts |
| `web` | Research preferences and earlier owned research summaries | Fetch current authorized URLs; do not leak private memories into outgoing tool arguments |

Memory supports every profile, but it does not change deterministic agents into LLM agents or make historical preferences permission to perform an action.

Direct `/tasks` and `/sql/query` gain an optional owned `conversation_id` for continuity. Authenticated one-shot calls may read approved personal memory when enabled; they do not automatically create personal memories from arbitrary task outputs. Parsing, raw SQL execution, and tool endpoints stay deterministic and do not acquire implicit memory behavior.

## 8. Semantic index and background work

Use a reserved memory collection, separate from uploaded-document RAG. It is not exposed through ordinary document collection listing/search/deletion. Payload includes account ID, memory/source ID, revision, kind, and scope. Maintain embedding model identity metadata and rebuild the derived index if that identity changes.

Apply the authenticated account filter at vector search time, including all dense/sparse branches if hybrid search is used. Recheck returned IDs, revisions, expiry, and ownership against SQL before use. Qdrant supports payload-based tenant filtering; the application must supply the correct filter consistently. [Qdrant multitenancy documentation](https://qdrant.tech/documentation/manage-data/multitenancy/).

Persist summary/extraction/index jobs in a database outbox. A bounded worker can run within the existing backend process; no extra queue service is needed initially. Claim jobs transactionally, use retry backoff and attempt limits, recover leases after restart, and deduplicate by source/revision/operation. Never use an untracked background task as the only record of pending work.

Prioritize user inference over background summarization. The earlier Docker tests demonstrated memory pressure when multiple large Ollama models were loaded, so start with one background inference job at a time and coordinate inference admission. Reuse an installed approved model and avoid unnecessary model swaps.

If indexing or optional extraction fails, chat can continue with owned recent history and saved SQL facts; report the reduced recall capability. Authentication/ownership failures always fail closed. An explicit memory save that fails must return an error and must not display “remembered.” A transcript commit failure must not produce a successful durable completion.

Log operation IDs, status, and latency rather than personal memory text or credentials. Track queue age, retries, memory context size, and recall availability so silent failures are visible.

## 9. Proposed API and UI changes

All new paths are under `/api/v1`:

| Interface | Purpose |
|---|---|
| `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | Session lifecycle and current account |
| `GET /memory`, `POST /memory` | Paginated owned memories and explicit reviewed saves |
| `PATCH /memory/{id}`, `DELETE /memory/{id}` | Revision-aware correction and forgetting |
| `DELETE /memory` | Confirmed deletion of all personal memory and derived recall data |
| `GET /memory/settings`, `PATCH /memory/settings` | Account memory preferences |

Extend existing conversation responses with memory eligibility and summary availability. Response execution metadata can report the memory IDs/source labels used; do not expose another account's existence. WebSocket completion carries equivalent metadata. Background suggestions appear on the Memory page after refresh/polling; they do not need to block answer streaming.

Frontend changes include login, an owned conversation list, resume-after-refresh, New Chat, memory settings, Remember this, and source-linked memory details. Store only an active conversation pointer locally; load messages from the authorized backend. Clear account-specific state, conversation pointers, and in-flight requests when signing out or switching accounts. Handle expired WebSocket sessions visibly.

## 10. Five implementation checkpoints

The initial planning estimate was roughly 11–16 working days. Treat it as a non-binding reference, not a time limit; implementation continues until the acceptance gates pass. The actual effort depends on the desktop client and migration needs.

| Stage | Deliverable | Acceptance gate | Estimate |
|---|---|---|---|
| 1. Identity and ownership | Accounts/sessions, migration, authorized routes/tools/resources, frontend login | Account B cannot access A's chats, assets, collections, SQL connections, workspace, meetings, or memory through REST, WS, or tools | 3–5 days |
| 2. Conversation continuity | Owned conversation browser/resume, stable turn ordering, bounded history and summaries | Refresh, reconnect, profile changes, and restart preserve the right conversation without duplicates or context overflow | 2–3 days |
| 3. Explicit saved memory | SQL records, reviewed save/edit/delete, account settings, shared MemoryContext | A saved preference affects a new conversation across relevant profiles; corrections and forgetting take effect immediately | 2 days |
| 4. Past-chat recall | Eligible summaries, Qdrant index, durable outbox worker, source links | Relevant owned past discussion is recalled after restart; queued jobs recover and deleted sources never resurface | 2–3 days |
| 5. Full-stack verification | Migration checks, account isolation matrix, real Ollama/browser tests, docs | Complete release gates below pass and remaining provider-specific gaps are stated | 2–3 days |

Each checkpoint should be a small reviewed diff with the associated checks. Implementation is authorized; use a feature branch with verified checkpoint commits and pushes, following the user's previously approved workflow. Do not commit application changes directly to `main`.

## 11. Test and release gates

### Deterministic tests

Extend the existing chat-continuity, profile, task, and RAG-context tests. Add account-isolation tests for every access surface, session expiry/revocation and CSRF tests, context-budget tests, and memory correction/deletion tests. Cover cross-account guessed IDs, guessed collection names, direct tools, parallel requests, duplicate client turns, delayed worker results, and jobs interrupted by restart.

Use controlled LLM responses for summary/extraction tests so assertions are reproducible. Treat remembered source statements as data and test an injected “ignore your rules” memory, malicious uploaded content, and a question asking for another person's secrets. Authorization must be deterministic; it must not depend on the model obeying instructions.

### Docker, Ollama, and browser scenarios

1. Sign in as Alice, save a formatting preference and discuss a synthetic project decision. Open a new conversation and verify relevant recall, then refresh and restart the backend/Compose stack with volumes retained.
2. Sign in as Bob in a separate browser context. Verify Alice's synthetic canary fact never appears and every attempted direct resource access is rejected.
3. Edit Alice's preference, delete the project memory/source conversation, and verify neither stale SQL nor stale vector results are used. Repeat while an extraction job is pending.
4. Exercise every profile through both applicable chat and direct-task routes. Verify deterministic image checks/workflow execution, RAG citations, SQL authorization, and current external data semantics remain correct.
5. Interrupt Ollama, Qdrant, a worker job, and a WebSocket. Verify honest availability/error reporting, retry recovery, durable completion ordering, and acceptable latency with Docker's memory limits.

The Alice/Bob account switch and recalled-source navigation passed in Safari. Stopping Ollama and Qdrant individually made `/health` report degraded and each service unavailable; restarting restored both. Expired summary/vector cleanup leases and WebSocket session handling are covered by deterministic tests. Playwright's 13 browser tests could not launch because Chromium's framework bundle is missing and the installer stalls after downloading its archive; this tooling limitation is recorded rather than treated as an application failure. Successful Finnhub and ComfyUI scenarios require a real configured key/service; their error paths are tested and are not counted as successful provider integration. Load latency under Docker memory limits was not benchmarked; a prior cold summary attempt timed out safely and succeeded on retry after model warm-up.

The release passes only when each account can recall its own saved facts and relevant past discussions across sessions, another account cannot read them, forgetting prevents future recall, and existing agent functionality still passes its checks.

## 12. Deferred scope and known limits

Do not add model fine-tuning, a knowledge graph, autonomous self-editing memories, team-shared personal memory, or a second transcript persistence system. Meeting-to-memory extraction is deferred because it requires a separate participant/consent policy; account ownership is still enforced for meeting access.

Summaries and semantic recall cannot guarantee perfect recollection of every past sentence. Keep source links and on-demand verification available. Host administrators with database/volume access can inspect stored data; account isolation is not encryption against the server operator. Existing backups retain data according to their retention policy.
