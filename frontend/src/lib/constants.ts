export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";
export const API_V1 = `${API_BASE}/api/v1`;
// WebSocket connects directly to the backend — Next.js rewrites only proxy HTTP.
// In production, set NEXT_PUBLIC_WS_URL to the backend's WebSocket address.
export const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";
export const WS_CHAT = `${WS_BASE}/api/v1/chat/stream`;

export const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50MB

export const ACCEPTED_FILE_TYPES = [
  ".pdf", ".docx", ".xlsx", ".pptx", ".csv",
  ".html", ".md", ".txt", ".png", ".jpg", ".jpeg", ".tiff", ".bmp",
];

export const AGENT_LABELS: Record<string, string> = {
  chat: "Chat",
  sql: "SQL Agent",
  document: "Document Agent",
  rag: "RAG Agent",
  web: "Web Research",
};

export const AGENT_COLORS: Record<string, string> = {
  chat: "bg-blue-500",
  sql: "bg-emerald-500",
  document: "bg-amber-500",
  rag: "bg-violet-500",
  web: "bg-rose-500",
};
