import { API_V1 } from "./constants";
import type { z } from "zod";
import {
  healthSchema,
  chatResponseSchema,
  conversationsListSchema,
  conversationDetailSchema,
  analysisResultSchema,
  documentListSchema,
  sqlQueryResponseSchema,
  sqlResultSetSchema,
  sqlSchemaResponseSchema,
  sqlConnectionsSchema,
  sqlAddConnectionSchema,
  ragSearchResultSchema,
  ragIngestSchema,
  ragCollectionsSchema,
  toolsListSchema,
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
  const res = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(
      body?.error?.code ?? "UNKNOWN_ERROR",
      body?.error?.message ?? res.statusText,
      res.status,
    );
  }

  const data = await res.json();

  if (schema) {
    return schema.parse(data) as T;
  }

  return data as T;
}

// --- Chat ---
export async function sendMessage(message: string, conversationId?: string) {
  return apiFetch("/chat", {
    method: "POST",
    body: JSON.stringify({ message, conversation_id: conversationId }),
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

// --- Documents ---
export async function uploadDocument(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  const url = `${API_V1}/documents/upload`;
  const res = await fetch(url, { method: "POST", body: formData });
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
    body: JSON.stringify({ query, database }),
  }, sqlQueryResponseSchema);
}

export async function executeSQL(sql: string, database?: string) {
  return apiFetch("/sql/execute", {
    method: "POST",
    body: JSON.stringify({ sql, database }),
  }, sqlResultSetSchema);
}

export async function getSQLSchema(database?: string) {
  const params = database ? `?database=${database}` : "";
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
export async function searchRAG(query: string, collection?: string, topK?: number) {
  return apiFetch("/rag/search", {
    method: "POST",
    body: JSON.stringify({ query, collection, top_k: topK }),
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
