import { API_V1 } from "./constants";
import { getCsrfToken } from "./auth-session";
import type { z } from "zod";
import {
  healthSchema,
  chatResponseSchema,
  conversationsListSchema,
  conversationDetailSchema,
  analysisResultSchema,
  documentListSchema,
  sqlQueryResponseSchema,
  sqlExecuteResponseSchema,
  sqlSchemaResponseSchema,
  sqlConnectionsSchema,
  sqlAddConnectionSchema,
  ragSearchResultSchema,
  ragIngestSchema,
  ragCollectionsSchema,
  toolsListSchema,
  agentCatalogSchema,
  memoryListSchema,
  memorySchema,
  memorySettingsSchema,
  memoryDeleteAllSchema,
  actionItemListSchema,
  actionItemSchema,
  actionItemProposalSchema,
  meetingSourceListSchema,
  githubConnectionSchema,
  githubAuthorizationSchema,
  conversationMemorySettingsSchema,
  type MemoryRecord,
  type MemorySettings,
  type ActionItemRecord,
} from "./schemas";

class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public statusCode: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function apiFetch<T>(
  path: string,
  options?: RequestInit,
  schema?: z.ZodType<T>,
): Promise<T> {
  const url = `${API_V1}${path}`;
  const method = options?.method ?? "GET";
  const csrfToken = getCsrfToken();
  const res = await fetch(url, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(method !== "GET" && csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
      ...options?.headers,
    },
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(
      body?.error?.code ?? "UNKNOWN_ERROR",
      body?.error?.message ?? body?.detail ?? res.statusText,
      res.status,
    );
  }

  if (res.status === 204) return undefined as T;

  const data = await res.json();

  if (schema) {
    return schema.parse(data) as T;
  }

  return data as T;
}

export interface AuthAccount {
  id: string;
  username: string;
  display_name: string;
}

export interface AuthSessionResponse {
  account: AuthAccount;
  csrf_token: string;
}

export async function login(username: string, password: string) {
  return apiFetch<AuthSessionResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function getCurrentAccount() {
  return apiFetch<AuthSessionResponse>("/auth/me");
}

export async function logout() {
  return apiFetch<void>("/auth/logout", { method: "POST" });
}

// --- Chat ---
export async function sendMessage(message: string, conversationId?: string) {
  return apiFetch("/chat", {
    method: "POST",
    body: JSON.stringify({ content: message, conversation_id: conversationId }),
  }, chatResponseSchema);
}

export async function getConversations() {
  return apiFetch("/chat/conversations", undefined, conversationsListSchema);
}

export async function getConversation(id: string) {
  return apiFetch(`/chat/conversations/${id}`, undefined, conversationDetailSchema);
}

export async function deleteConversation(id: string) {
  return apiFetch<{ deleted: boolean }>(`/chat/conversations/${id}`, { method: "DELETE" });
}

export async function getAgentCatalog() {
  return apiFetch("/agents", undefined, agentCatalogSchema);
}

// --- Account memory ---
export async function getMemories(q?: string) {
  const params = new URLSearchParams({ limit: "100" });
  if (q?.trim()) params.set("q", q.trim());
  return apiFetch(`/memory?${params}`, undefined, memoryListSchema);
}

export async function createMemory(input: {
  kind: MemoryRecord["kind"];
  content: string;
  project_scope?: string;
  source_conversation_id?: string;
  source_message_id?: string;
  source_client_turn_id?: string;
}) {
  return apiFetch("/memory", {
    method: "POST",
    body: JSON.stringify(input),
  }, memorySchema);
}

export async function updateMemory(
  id: string,
  input: { revision: number; content?: string; kind?: MemoryRecord["kind"]; project_scope?: string | null },
) {
  return apiFetch(`/memory/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  }, memorySchema);
}

export async function deleteMemory(id: string, revision: number) {
  return apiFetch<void>(`/memory/${encodeURIComponent(id)}?revision=${revision}`, { method: "DELETE" });
}

// --- Action item planner ---
export async function getActionItems() {
  return apiFetch("/action-items", undefined, actionItemListSchema);
}

export async function createActionItem(input: {
  title: string;
  description?: string;
  priority?: ActionItemRecord["priority"];
  due_date?: string;
  source_type?: ActionItemRecord["source_type"];
  source_id?: string;
  source_quote?: string;
}) {
  return apiFetch("/action-items", {
    method: "POST",
    body: JSON.stringify(input),
  }, actionItemSchema);
}

export async function proposeActionItems(input: {
  source_type: "chat" | "meeting" | "document";
  source_id: string;
}) {
  return apiFetch("/action-items/proposals", {
    method: "POST",
    body: JSON.stringify(input),
  }, actionItemProposalSchema);
}

export async function getMeetings() {
  return apiFetch("/meetings", undefined, meetingSourceListSchema);
}

// --- GitHub App connection ---
export async function getGitHubConnection() {
  return apiFetch("/github/connection", undefined, githubConnectionSchema);
}

export async function startGitHubConnection() {
  return apiFetch("/github/connect", { method: "POST" }, githubAuthorizationSchema);
}

export async function disconnectGitHub() {
  return apiFetch<void>("/github/connection", { method: "DELETE" });
}

export async function updateActionItem(
  id: string,
  input: {
    revision: number;
    title?: string;
    description?: string | null;
    status?: ActionItemRecord["status"];
    priority?: ActionItemRecord["priority"];
    due_date?: string | null;
  },
) {
  return apiFetch(`/action-items/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  }, actionItemSchema);
}

export async function deleteActionItem(id: string) {
  return apiFetch<void>(`/action-items/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function getMemorySettings() {
  return apiFetch("/memory/settings", undefined, memorySettingsSchema);
}

export async function updateMemorySettings(input: Partial<MemorySettings>) {
  return apiFetch("/memory/settings", {
    method: "PATCH",
    body: JSON.stringify(input),
  }, memorySettingsSchema);
}

export async function deleteAllMemories() {
  return apiFetch("/memory", { method: "DELETE" }, memoryDeleteAllSchema);
}

export async function updateConversationMemorySettings(
  conversationId: string,
  input: { exclude_from_memory: boolean },
) {
  return apiFetch(`/memory/conversations/${encodeURIComponent(conversationId)}/settings`, {
    method: "PATCH",
    body: JSON.stringify(input),
  }, conversationMemorySettingsSchema);
}

// --- Documents ---
export async function uploadDocument(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  const url = `${API_V1}/documents/upload`;
  const csrfToken = getCsrfToken();
  const res = await fetch(url, {
    method: "POST",
    body: formData,
    credentials: "include",
    headers: csrfToken ? { "X-CSRF-Token": csrfToken } : {},
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(
      body?.error?.code ?? "UPLOAD_ERROR",
      body?.error?.message ?? res.statusText,
      res.status,
    );
  }
  return res.json();
}

export async function getDocuments() {
  return apiFetch("/documents", undefined, documentListSchema);
}

export async function getDocument(id: string) {
  return apiFetch<unknown>(`/documents/${id}`);
}

export async function analyzeDocument(id: string, prompt?: string) {
  return apiFetch(`/documents/${id}/analyze`, {
    method: "POST",
    body: JSON.stringify({ prompt }),
  }, analysisResultSchema);
}

export async function deleteDocument(id: string) {
  return apiFetch<{ deleted: boolean }>(`/documents/${id}`, { method: "DELETE" });
}

// --- SQL ---
export async function querySQL(query: string, database?: string) {
  return apiFetch("/sql/query", {
    method: "POST",
    body: JSON.stringify({ question: query, database }),
  }, sqlQueryResponseSchema);
}

export async function executeSQL(sql: string, database?: string) {
  return apiFetch("/sql/execute", {
    method: "POST",
    body: JSON.stringify({ sql, database }),
  }, sqlExecuteResponseSchema);
}

export async function getSQLSchema(database?: string) {
  const params = database ? `?database=${encodeURIComponent(database)}` : "";
  return apiFetch(`/sql/schema${params}`, undefined, sqlSchemaResponseSchema);
}

export async function getSQLConnections() {
  return apiFetch("/sql/connections", undefined, sqlConnectionsSchema);
}

export async function addSQLConnection(name: string, url: string) {
  return apiFetch("/sql/connections", {
    method: "POST",
    body: JSON.stringify({ name, url }),
  }, sqlAddConnectionSchema);
}

// --- RAG ---
export async function searchRAG(
  query: string,
  collection?: string,
  topK?: number,
  agentName = "rag",
) {
  return apiFetch("/rag/search", {
    method: "POST",
    body: JSON.stringify({ query, collection, top_k: topK, agent_name: agentName }),
  }, ragSearchResultSchema);
}

export async function ingestRAG(documentId: string, collection?: string) {
  return apiFetch("/rag/ingest", {
    method: "POST",
    body: JSON.stringify({ document_id: documentId, collection }),
  }, ragIngestSchema);
}

export async function getRAGCollections() {
  return apiFetch("/rag/collections", undefined, ragCollectionsSchema);
}

export async function deleteRAGCollection(name: string) {
  return apiFetch<{ deleted: boolean }>(`/rag/collections/${name}`, { method: "DELETE" });
}

// --- Health ---
export async function getHealth() {
  return apiFetch("/health", undefined, healthSchema);
}

// --- Tools ---
export async function getTools() {
  return apiFetch("/tools", undefined, toolsListSchema);
}

export { ApiError };
