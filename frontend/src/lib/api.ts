import { API_V1 } from "./constants";
import { getCsrfToken } from "./auth-session";
import { z } from "zod";
import {
  healthSchema,
  chatResponseSchema,
  conversationsListSchema,
  conversationDetailSchema,
  analysisResultSchema,
  documentListSchema,
  uploadResultSchema,
  redactionJobSchema,
  redactionReviewSchema,
  sqlQueryResponseSchema,
  sqlExecuteResponseSchema,
  sqlSchemaResponseSchema,
  sqlConnectionsSchema,
  sqlAddConnectionSchema,
  ragSearchResultSchema,
  ragIngestSchema,
  ragCollectionsSchema,
  ragContainerFileSchema,
  ragContainerSchema,
  ragContainersSchema,
  ragContainerUploadResultSchema,
  ragContainerLoadSchema,
  deleteResultSchema,
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
  githubRepositoryListSchema,
  githubProjectOverviewSchema,
  githubPullDetailSchema,
  githubIssueProposalSchema,
  githubIssueWriteSchema,
  githubCommentWriteSchema,
  conversationMemorySettingsSchema,
  type MemoryRecord,
  type MemorySettings,
  type ActionItemRecord,
} from "./schemas";

export type RAGContainer = z.infer<typeof ragContainerSchema>;
export type RAGContainerFile = z.infer<typeof ragContainerFileSchema>;

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

export async function getConversations(limit = 50, offset = 0, query = "") {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (query.trim()) params.set("q", query.trim());
  return apiFetch(`/chat/conversations?${params}`, undefined, conversationsListSchema);
}

export async function getConversation(id: string) {
  return apiFetch(`/chat/conversations/${id}`, undefined, conversationDetailSchema);
}

export async function deleteConversation(id: string) {
  return apiFetch<{ status: "deleted"; conversation_id: string }>(`/chat/conversations/${id}`, { method: "DELETE" });
}

export async function getAgentCatalog() {
  return apiFetch("/agents", undefined, agentCatalogSchema);
}

export async function getAgentCatalogWithArchived() {
  return apiFetch("/agents?include_archived=true", undefined, agentCatalogSchema);
}

export async function createAgent(input: {
  source_agent: string;
  display_name: string;
  description: string;
}) {
  return apiFetch("/agents", { method: "POST", body: JSON.stringify(input) }, agentCatalogSchema);
}

export async function updateAgent(name: string, input: {
  display_name?: string;
  description?: string;
  system_prompt?: string | null;
  archived?: boolean;
}) {
  return apiFetch(`/agents/${encodeURIComponent(name)}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  }, agentCatalogSchema);
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
  const items: ActionItemRecord[] = [];
  let offset = 0;
  let total = 0;

  do {
    const page = await apiFetch(
      `/action-items?limit=200&offset=${offset}`,
      undefined,
      actionItemListSchema,
    );
    items.push(...page.items);
    total = page.total;
    offset += page.items.length;
    if (!page.items.length) break;
  } while (offset < total);

  return { items, total };
}

export async function createActionItem(input: {
  title: string;
  description?: string;
  priority?: ActionItemRecord["priority"];
  due_date?: string;
  source_type?: ActionItemRecord["source_type"];
  source_id?: string;
  source_repository_id?: string;
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

export async function getGitHubRepositories() {
  return apiFetch("/github/repositories", undefined, githubRepositoryListSchema);
}

export async function setGitHubRepositorySelection(repositoryId: string, selected: boolean) {
  return apiFetch<void>(`/github/repositories/${encodeURIComponent(repositoryId)}/selection`, {
    method: "PUT",
    body: JSON.stringify({ selected }),
  });
}

export async function getGitHubProjectOverview(repositoryId: string) {
  return apiFetch(`/github/agent/repositories/${encodeURIComponent(repositoryId)}`, undefined, githubProjectOverviewSchema);
}

export async function getGitHubPullDetail(repositoryId: string, number: number) {
  return apiFetch(`/github/agent/repositories/${encodeURIComponent(repositoryId)}/pulls/${number}`, undefined, githubPullDetailSchema);
}

export async function proposeGitHubIssueActions(repositoryId: string, number: number) {
  return apiFetch(`/github/agent/repositories/${encodeURIComponent(repositoryId)}/issues/${number}/proposals`, { method: "POST" }, githubIssueProposalSchema);
}

export async function createGitHubIssue(repositoryId: string, input: { title: string; body: string }) {
  return apiFetch(`/github/agent/repositories/${encodeURIComponent(repositoryId)}/issues`, {
    method: "POST",
    body: JSON.stringify(input),
  }, githubIssueWriteSchema);
}

export async function createGitHubIssueComment(repositoryId: string, issueNumber: number, body: string) {
  return apiFetch(`/github/agent/repositories/${encodeURIComponent(repositoryId)}/issues/${issueNumber}/comments`, {
    method: "POST",
    body: JSON.stringify({ body }),
  }, githubCommentWriteSchema);
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
  return uploadResultSchema.parse(await res.json());
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

export async function createRedactionJob(input: {
  document_id: string;
  categories: string[];
  instructions: string;
}) {
  return apiFetch("/redaction-jobs", {
    method: "POST",
    body: JSON.stringify(input),
  }, redactionJobSchema);
}

export async function getRedactionJob(id: string) {
  return apiFetch(`/redaction-jobs/${encodeURIComponent(id)}`, undefined, redactionJobSchema);
}

export async function getRedactionReview(id: string) {
  return apiFetch(`/redaction-jobs/${encodeURIComponent(id)}/review`, undefined, redactionReviewSchema);
}

export async function clarifyRedactionJob(jobId: string, answer: string) {
  return apiFetch(`/redaction-jobs/${encodeURIComponent(jobId)}/clarify`, {
    method: "POST",
    body: JSON.stringify({ answer }),
  }, redactionJobSchema);
}

export async function updateRedactionFinding(
  jobId: string,
  findingId: string,
  input: { selected: boolean; boxes: number[][] },
) {
  return apiFetch(`/redaction-jobs/${encodeURIComponent(jobId)}/findings/${encodeURIComponent(findingId)}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  }, redactionJobSchema);
}

export async function addRedactionBox(jobId: string, page_number: number, box: number[]) {
  return apiFetch(`/redaction-jobs/${encodeURIComponent(jobId)}/manual-boxes`, {
    method: "POST",
    body: JSON.stringify({ page_number, box }),
  }, redactionJobSchema);
}

export async function retryRedactionPage(jobId: string, page_number: number) {
  return apiFetch(`/redaction-jobs/${encodeURIComponent(jobId)}/retry-page`, {
    method: "POST",
    body: JSON.stringify({ page_number }),
  }, redactionJobSchema);
}

export async function resolveRedactionPage(jobId: string, page_number: number) {
  return apiFetch(`/redaction-jobs/${encodeURIComponent(jobId)}/resolve-page`, {
    method: "POST",
    body: JSON.stringify({ page_number }),
  }, redactionJobSchema);
}

export async function approveRedactionReview(jobId: string, revision: number) {
  return apiFetch(`/redaction-jobs/${encodeURIComponent(jobId)}/approve?revision=${revision}`, {
    method: "POST",
  }, redactionJobSchema);
}

export async function exportRedactedDocument(jobId: string) {
  return apiFetch(`/redaction-jobs/${encodeURIComponent(jobId)}/export`, {
    method: "POST",
  }, redactionJobSchema);
}

export async function cancelRedactionJob(jobId: string) {
  return apiFetch(`/redaction-jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  }, redactionJobSchema);
}

export async function getRedactionPreviewUrl(jobId: string, pageNumber: number) {
  const response = await fetch(
    `${API_V1}/redaction-jobs/${encodeURIComponent(jobId)}/pages/${pageNumber}/preview`,
    { credentials: "include" },
  );
  if (!response.ok) throw new Error("Could not load the page preview.");
  return URL.createObjectURL(await response.blob());
}

export async function downloadRedactedDocument(jobId: string) {
  const response = await fetch(`${API_V1}/redaction-jobs/${encodeURIComponent(jobId)}/download`, {
    credentials: "include",
  });
  if (!response.ok) throw new Error("Could not download the redacted document.");
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] ?? "redacted.pdf";
  return { blob: await response.blob(), filename };
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

export async function getRAGContainers() {
  return apiFetch("/rag/containers", undefined, ragContainersSchema);
}

export async function createRAGContainer(displayName: string) {
  return apiFetch("/rag/containers", {
    method: "POST",
    body: JSON.stringify({ display_name: displayName }),
  }, ragContainerSchema);
}

export async function getRAGContainerFiles(name: string) {
  return apiFetch(
    `/rag/containers/${encodeURIComponent(name)}/files`,
    undefined,
    z.array(ragContainerFileSchema),
  );
}

export async function uploadRAGContainerFiles(
  name: string,
  entries: Array<{ file: File; relativePath: string }>,
) {
  const formData = new FormData();
  for (const { file, relativePath } of entries) {
    formData.append("files", file, file.name);
    formData.append("relative_paths", relativePath);
  }
  const csrfToken = getCsrfToken();
  const response = await fetch(`${API_V1}/rag/containers/${encodeURIComponent(name)}/files`, {
    method: "POST",
    body: formData,
    credentials: "include",
    headers: csrfToken ? { "X-CSRF-Token": csrfToken } : {},
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      body?.error?.code ?? "UPLOAD_ERROR",
      body?.error?.message ?? body?.detail ?? response.statusText,
      response.status,
    );
  }
  return ragContainerUploadResultSchema.parse(await response.json());
}

export async function loadRAGContainer(name: string) {
  return apiFetch(
    `/rag/containers/${encodeURIComponent(name)}/load`,
    { method: "POST" },
    ragContainerLoadSchema,
  );
}

export async function queueDocumentInRAGContainer(name: string, documentId: string) {
  return apiFetch(
    `/rag/containers/${encodeURIComponent(name)}/documents/${encodeURIComponent(documentId)}`,
    { method: "POST" },
    ragContainerFileSchema,
  );
}

export async function retryRAGContainerFile(name: string, fileId: string) {
  return apiFetch(
    `/rag/containers/${encodeURIComponent(name)}/files/${encodeURIComponent(fileId)}/retry`,
    { method: "POST" },
    ragContainerFileSchema,
  );
}

export async function deleteRAGContainerFile(name: string, fileId: string) {
  return apiFetch(
    `/rag/containers/${encodeURIComponent(name)}/files/${encodeURIComponent(fileId)}`,
    { method: "DELETE" },
    deleteResultSchema,
  );
}

export async function deleteRAGContainer(name: string) {
  return apiFetch(
    `/rag/containers/${encodeURIComponent(name)}`,
    { method: "DELETE" },
    deleteResultSchema,
  );
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
