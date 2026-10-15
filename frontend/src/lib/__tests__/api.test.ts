import { describe, it, expect, vi, afterEach } from "vitest";

// Must import after mocking fetch
import {
  sendMessage,
  getConversations,
  getConversation,
  deleteConversation,
  uploadDocument,
  getDocuments,
  getDocument,
  analyzeDocument,
  deleteDocument,
  querySQL,
  executeSQL,
  getSQLSchema,
  getSQLConnections,
  addSQLConnection,
  searchRAG,
  ingestRAG,
  getRAGCollections,
  deleteRAGCollection,
  getHealth,
  getTools,
  getAgentCatalog,
  getMemories,
  createMemory,
  updateMemory,
  deleteMemory,
  getMemorySettings,
  updateMemorySettings,
  deleteAllMemories,
  updateConversationMemorySettings,
  getActionItems,
  login,
  logout,
  ApiError,
} from "../api";
import { setCsrfToken } from "../auth-session";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockFetchSuccess(body: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status,
    json: () => Promise.resolve(body),
  });
}

function mockFetchError(body: unknown, status = 500, statusText = "Server Error") {
  return vi.fn().mockResolvedValue({
    ok: false,
    status,
    statusText,
    json: () => Promise.resolve(body),
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("API Client", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    setCsrfToken(null);
    vi.restoreAllMocks();
  });

  // ---- apiFetch / generic behaviour ----------------------------------------

  describe("apiFetch wrapper", () => {
    it("sets Content-Type header to application/json", async () => {
      const spy = mockFetchSuccess([]);
      globalThis.fetch = spy;

      await getTools();

      const [, init] = spy.mock.calls[0];
      expect(init.headers["Content-Type"]).toBe("application/json");
      expect(init.credentials).toBe("include");
    });

    it("throws ApiError with code from response body on non-200", async () => {
      globalThis.fetch = mockFetchError(
        { error: { code: "NOT_FOUND", message: "Not found" } },
        404,
        "Not Found",
      );

      await expect(getTools()).rejects.toThrow(ApiError);
      try {
        await getTools();
      } catch (err) {
        expect(err).toBeInstanceOf(ApiError);
        expect((err as InstanceType<typeof ApiError>).code).toBe("NOT_FOUND");
        expect((err as InstanceType<typeof ApiError>).statusCode).toBe(404);
        expect((err as InstanceType<typeof ApiError>).message).toBe("Not found");
      }
    });

    it("falls back to UNKNOWN_ERROR when body cannot be parsed", async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        json: () => Promise.reject(new Error("bad json")),
      });

      try {
        await getTools();
      } catch (err) {
        expect((err as InstanceType<typeof ApiError>).code).toBe("UNKNOWN_ERROR");
        expect((err as InstanceType<typeof ApiError>).message).toBe("Internal Server Error");
      }
    });
  });

  // ---- Chat -----------------------------------------------------------------

  describe("Chat endpoints", () => {
    it("sends the session CSRF token with mutations", async () => {
      const spy = mockFetchSuccess({ status: "deleted", conversation_id: "c1" });
      globalThis.fetch = spy;
      setCsrfToken("session-csrf");

      await deleteConversation("c1");

      expect(spy.mock.calls[0][1].headers["X-CSRF-Token"]).toBe("session-csrf");
    });

    it("deletes a conversation by id", async () => {
      const spy = mockFetchSuccess({ status: "deleted", conversation_id: "c1" });
      globalThis.fetch = spy;

      await expect(deleteConversation("c1")).resolves.toEqual({
        status: "deleted",
        conversation_id: "c1",
      });
      expect(spy.mock.calls[0][0]).toContain("/chat/conversations/c1");
      expect(spy.mock.calls[0][1].method).toBe("DELETE");
    });

    it("sendMessage posts to /chat with message and conversationId", async () => {
      const spy = mockFetchSuccess({ content: "hi", conversation_id: "c1", agent_used: "chat" });
      globalThis.fetch = spy;

      const result = await sendMessage("hello", "c1");

      expect(result.content).toBe("hi");
      const [url, init] = spy.mock.calls[0];
      expect(url).toContain("/chat");
      expect(JSON.parse(init.body)).toEqual({ content: "hello", conversation_id: "c1" });
    });

    it("loads the enabled profile catalog", async () => {
      const spy = mockFetchSuccess({ agents: [
        { name: "rag_v2", target: "rag", description: "Hybrid retrieval", default_for_target: false, inference: null },
      ] });
      globalThis.fetch = spy;
      const result = await getAgentCatalog();
      expect(result.agents[0].name).toBe("rag_v2");
      expect(spy.mock.calls[0][0]).toContain("/agents");
    });

    it("sendMessage works without conversationId", async () => {
      const spy = mockFetchSuccess({ content: "ok", conversation_id: "c2", agent_used: "chat" });
      globalThis.fetch = spy;

      await sendMessage("test");

      const body = JSON.parse(spy.mock.calls[0][1].body);
      expect(body.content).toBe("test");
      expect(body.conversation_id).toBeUndefined();
    });

    it("getConversations fetches conversation list", async () => {
      const data = [{ id: "1", title: "Test", created_at: "", last_message_at: "", message_count: 2 }];
      globalThis.fetch = mockFetchSuccess(data);

      const result = await getConversations();
      expect(result.conversations).toHaveLength(1);
    });

    it("getConversations includes the page and search query", async () => {
      const spy = mockFetchSuccess([]);
      globalThis.fetch = spy;

      await getConversations(50, 50, "  project  ");

      expect(spy.mock.calls[0][0]).toContain("limit=50");
      expect(spy.mock.calls[0][0]).toContain("offset=50");
      expect(spy.mock.calls[0][0]).toContain("q=project");
    });

    it("getConversation fetches single conversation", async () => {
      globalThis.fetch = mockFetchSuccess({
        id: "1",
        title: "t",
        messages: [{
          id: "message-1",
          role: "assistant",
          content: "Answer",
          agent_type: "chat",
          execution: null,
          created_at: "2026-10-12T10:00:00Z",
          tool_calls: [{
            id: "tool-1",
            tool_name: "search",
            tool_input: { query: "topic" },
            tool_output: "result",
            duration_ms: 5,
          }],
        }],
      });

      const result = await getConversation("1");
      expect(result.id).toBe("1");
      expect(result.messages[0].tool_calls[0].tool_name).toBe("search");
    });

    it("deleteConversation sends DELETE request", async () => {
      const spy = mockFetchSuccess({ status: "deleted", conversation_id: "1" });
      globalThis.fetch = spy;

      const result = await deleteConversation("1");

      expect(result.status).toBe("deleted");
      expect(result.conversation_id).toBe("1");
      expect(spy.mock.calls[0][1].method).toBe("DELETE");
    });
  });

  describe("Memory endpoints", () => {
    it("searches owned memories with encoded query parameters", async () => {
      const spy = mockFetchSuccess({ memories: [], total: 0, limit: 100, offset: 0 });
      globalThis.fetch = spy;
      await getMemories("project cedar");
      expect(spy.mock.calls[0][0]).toContain("/memory?limit=100&q=project+cedar");
    });

    it("creates, edits, and deletes a memory using revision checks", async () => {
      const record = {
        id: "m1", kind: "fact", content: "Uses blue", project_scope: null,
        source_conversation_id: null, source_message_id: null, origin_agent: null,
        created_at: "2026-10-12T00:00:00Z", updated_at: "2026-10-12T00:00:00Z",
        expires_at: null, revision: 1,
      };
      const spy = mockFetchSuccess(record);
      globalThis.fetch = spy;
      await createMemory({
        kind: "fact",
        content: "Uses blue",
        source_conversation_id: "conversation-1",
        source_client_turn_id: "turn-1",
      });
      await updateMemory("m1", { revision: 1, content: "Uses cobalt blue" });
      expect(JSON.parse(spy.mock.calls[0][1].body)).toEqual({
        kind: "fact",
        content: "Uses blue",
        source_conversation_id: "conversation-1",
        source_client_turn_id: "turn-1",
      });
      expect(JSON.parse(spy.mock.calls[1][1].body)).toEqual({ revision: 1, content: "Uses cobalt blue" });
      const deleteSpy = mockFetchSuccess(undefined, 204);
      globalThis.fetch = deleteSpy;
      await deleteMemory("m1", 1);
      expect(deleteSpy.mock.calls[0][0]).toContain("/memory/m1?revision=1");
    });

    it("gets and updates independent memory settings and clears memories", async () => {
      const spy = mockFetchSuccess({ memory_enabled: false, past_chat_recall_enabled: false });
      globalThis.fetch = spy;
      await getMemorySettings();
      await updateMemorySettings({ memory_enabled: true });
      expect(spy.mock.calls[1][0]).toContain("/memory/settings");
      expect(JSON.parse(spy.mock.calls[1][1].body)).toEqual({ memory_enabled: true });
      const deleteSpy = mockFetchSuccess({ deleted_count: 1, memory_epoch: 2, past_chat_recall_enabled: false });
      globalThis.fetch = deleteSpy;
      expect((await deleteAllMemories()).deleted_count).toBe(1);
      expect(deleteSpy.mock.calls[0][1].method).toBe("DELETE");
    });

    it("updates a conversation's cross-chat recall exclusion", async () => {
      const spy = mockFetchSuccess({ exclude_from_memory: true });
      globalThis.fetch = spy;
      const result = await updateConversationMemorySettings("conversation 1", { exclude_from_memory: true });
      expect(result.exclude_from_memory).toBe(true);
      expect(spy.mock.calls[0][0]).toContain("/memory/conversations/conversation%201/settings");
      expect(JSON.parse(spy.mock.calls[0][1].body)).toEqual({ exclude_from_memory: true });
    });
  });

  describe("Action item endpoints", () => {
    it("loads every page of action items", async () => {
      const item = (id: string) => ({
        id,
        title: `Task ${id}`,
        description: null,
        status: "next",
        priority: "normal",
        due_date: null,
        source_type: null,
        source_id: null,
        source_repository_id: null,
        source_quote: null,
        revision: 1,
        created_at: "2026-10-12T00:00:00Z",
        updated_at: "2026-10-12T00:00:00Z",
      });
      const spy = vi.fn()
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ items: Array.from({ length: 200 }, (_, i) => item(String(i))), total: 201 }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ items: [item("200")], total: 201 }),
        });
      globalThis.fetch = spy;

      const result = await getActionItems();

      expect(result.items).toHaveLength(201);
      expect(result.total).toBe(201);
      expect(spy.mock.calls[0][0]).toContain("/action-items?limit=200&offset=0");
      expect(spy.mock.calls[1][0]).toContain("/action-items?limit=200&offset=200");
    });
  });

  // ---- Documents ------------------------------------------------------------

  describe("Document endpoints", () => {
    it("uploadDocument sends FormData without Content-Type header", async () => {
      const spy = mockFetchSuccess({ id: "d1", filename: "test.pdf", format: "pdf", size_bytes: 100, status: "completed" });
      globalThis.fetch = spy as unknown as typeof fetch;

      const file = new File(["data"], "test.pdf", { type: "application/pdf" });
      const result = await uploadDocument(file);

      expect(result.id).toBe("d1");
      const [, init] = spy.mock.calls[0];
      expect(init.method).toBe("POST");
      expect(init.body).toBeInstanceOf(FormData);
      expect(init.credentials).toBe("include");
      // The browser sets Content-Type with the multipart boundary.
      expect(init.headers["Content-Type"]).toBeUndefined();
    });

    it("uploadDocument throws ApiError on failure", async () => {
      globalThis.fetch = mockFetchError(
        { error: { code: "UPLOAD_ERROR", message: "Too large" } },
        413,
        "Payload Too Large",
      );

      await expect(uploadDocument(new File(["x"], "big.pdf"))).rejects.toThrow(ApiError);
    });

    it("uploadDocument falls back to UPLOAD_ERROR when body parse fails", async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: "Error",
        json: () => Promise.reject(new Error("bad")),
      });

      try {
        await uploadDocument(new File(["x"], "f.pdf"));
      } catch (err) {
        expect((err as InstanceType<typeof ApiError>).code).toBe("UPLOAD_ERROR");
      }
    });

    it("getDocuments fetches document list", async () => {
      globalThis.fetch = mockFetchSuccess([{ id: "d1", filename: "f.txt", format: "txt", size_bytes: 1, status: "pending", created_at: "" }]);

      const result = await getDocuments();
      expect(result.documents).toHaveLength(1);
    });

    it("getDocument fetches single document", async () => {
      globalThis.fetch = mockFetchSuccess({ id: "d1", filename: "f.txt" });

      const result = await getDocument("d1");
      expect(result).toEqual({ id: "d1", filename: "f.txt" });
    });

    it("analyzeDocument posts to /documents/:id/analyze", async () => {
      const spy = mockFetchSuccess({
        document_id: "d1",
        filename: "report.pdf",
        format: "pdf",
        text: "looks good",
        tables: [],
        metadata: {},
        page_count: null,
        word_count: 100,
        status: "completed",
      });
      globalThis.fetch = spy;

      const result = await analyzeDocument("d1", "summarize");

      expect(result.text).toBe("looks good");
      const body = JSON.parse(spy.mock.calls[0][1].body);
      expect(body.prompt).toBe("summarize");
    });

    it("deleteDocument sends DELETE", async () => {
      const spy = mockFetchSuccess({ deleted: true });
      globalThis.fetch = spy;

      await deleteDocument("d1");
      expect(spy.mock.calls[0][1].method).toBe("DELETE");
    });
  });

  describe("Authentication endpoints", () => {
    it("logs in using credentials and returns the account CSRF token", async () => {
      const spy = mockFetchSuccess({
        account: { id: "account-1", username: "alice", display_name: "Alice" },
        csrf_token: "csrf-1",
      });
      globalThis.fetch = spy;

      const session = await login("alice", "password");

      expect(session.csrf_token).toBe("csrf-1");
      expect(JSON.parse(spy.mock.calls[0][1].body)).toEqual({ username: "alice", password: "password" });
      expect(spy.mock.calls[0][1].credentials).toBe("include");
    });

    it("accepts the empty 204 response from logout", async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, status: 204 });
      setCsrfToken("csrf-1");

      await expect(logout()).resolves.toBeUndefined();
      const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
      expect(fetchMock.mock.calls[0][1].headers["X-CSRF-Token"]).toBe("csrf-1");
    });
  });

  // ---- SQL ------------------------------------------------------------------

  describe("SQL endpoints", () => {
    it("querySQL posts query and database", async () => {
      const spy = mockFetchSuccess({ generated_sql: "SELECT 1", explanation: "test", columns: [], rows: [], row_count: 0 });
      globalThis.fetch = spy;

      const result = await querySQL("show customers", "demo");

      expect(result.sql).toBe("SELECT 1");
      const body = JSON.parse(spy.mock.calls[0][1].body);
      expect(body.question).toBe("show customers");
      expect(body.database).toBe("demo");
    });

    it("executeSQL posts raw SQL", async () => {
      const spy = mockFetchSuccess({ sql: "SELECT 1", result: { columns: ["id"], rows: [[1]], row_count: 1 } });
      globalThis.fetch = spy;

      const result = await executeSQL("SELECT 1");

      expect(result.row_count).toBe(1);
    });

    it("getSQLSchema includes database query param when provided", async () => {
      const spy = mockFetchSuccess({ database: "demo", tables: [] });
      globalThis.fetch = spy;

      await getSQLSchema("demo");

      expect(spy.mock.calls[0][0]).toContain("?database=demo");
    });

    it("getSQLSchema omits query param when no database given", async () => {
      const spy = mockFetchSuccess({ database: "default", tables: [] });
      globalThis.fetch = spy;

      await getSQLSchema();

      expect(spy.mock.calls[0][0]).not.toContain("?database=");
    });

    it("getSQLConnections returns connections", async () => {
      globalThis.fetch = mockFetchSuccess([{ name: "demo", url: "sqlite:///demo.db" }]);

      const result = await getSQLConnections();
      expect(result.connections).toHaveLength(1);
    });

    it("addSQLConnection posts name and url", async () => {
      const spy = mockFetchSuccess({ name: "new", status: "connected" });
      globalThis.fetch = spy;

      const result = await addSQLConnection("new", "sqlite:///new.db");

      expect(result.name).toBe("new");
      const body = JSON.parse(spy.mock.calls[0][1].body);
      expect(body).toEqual({ name: "new", url: "sqlite:///new.db" });
    });
  });

  // ---- RAG ------------------------------------------------------------------

  describe("RAG endpoints", () => {
    it("searchRAG posts query with optional params", async () => {
      const spy = mockFetchSuccess({ results: [], query: "test", total_results: 0 });
      globalThis.fetch = spy;

      await searchRAG("test", "docs", 10, "rag_v2");

      const body = JSON.parse(spy.mock.calls[0][1].body);
      expect(body).toEqual({ query: "test", collection: "docs", top_k: 10, agent_name: "rag_v2" });
    });

    it("ingestRAG posts document_id and collection", async () => {
      const spy = mockFetchSuccess({ document_id: "doc-123", collection: "mycol", chunks_ingested: 5 });
      globalThis.fetch = spy;

      const result = await ingestRAG("doc-123", "mycol");

      expect(result.chunks).toBe(5);
      const body = JSON.parse(spy.mock.calls[0][1].body);
      expect(body.document_id).toBe("doc-123");
      expect(body.collection).toBe("mycol");
    });

    it("getRAGCollections returns collections", async () => {
      globalThis.fetch = mockFetchSuccess([{ name: "c1", document_count: 10 }]);

      const result = await getRAGCollections();
      expect(result.collections[0].name).toBe("c1");
    });

    it("deleteRAGCollection sends DELETE", async () => {
      const spy = mockFetchSuccess({ deleted: true });
      globalThis.fetch = spy;

      await deleteRAGCollection("c1");
      expect(spy.mock.calls[0][1].method).toBe("DELETE");
      expect(spy.mock.calls[0][0]).toContain("/rag/collections/c1");
    });
  });

  // ---- Health & Tools -------------------------------------------------------

  describe("Health & Tools", () => {
    it("getHealth returns status", async () => {
      globalThis.fetch = mockFetchSuccess({
        status: "healthy",
        services: [
          { name: "ollama", healthy: true },
          { name: "qdrant", healthy: true },
          { name: "app_database", healthy: true },
        ],
        meeting_ready: true,
      });

      const result = await getHealth();
      expect(result.status).toBe("healthy");
    });

    it("getTools returns tool list", async () => {
      globalThis.fetch = mockFetchSuccess([{ name: "calc", description: "Calculator" }]);

      const result = await getTools();
      expect(result.tools).toHaveLength(1);
      expect(result.tools[0].name).toBe("calc");
    });
  });
});
