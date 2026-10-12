export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";
export const API_V1 = `${API_BASE}/api/v1`;
const sameOriginWebSocketBase =
  typeof window === "undefined"
    ? "ws://localhost:8000"
    : `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`;
export const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || sameOriginWebSocketBase;
export const WS_CHAT = `${WS_BASE}/api/v1/chat/stream`;
export const ACTIVE_CONVERSATION_STORAGE_PREFIX = "local-ai-active-conversation:";

export const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50MB

export const ACCEPTED_FILE_TYPES = [
  ".pdf", ".docx", ".xlsx", ".pptx", ".csv",
  ".html", ".md", ".txt", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp",
];

export const AGENT_LABELS: Record<string, string> = {
  chat: "Chat",
  sql: "SQL Agent",
  document: "Document Agent",
  rag: "RAG Agent",
  rag_v2: "RAG Agent v2",
  web: "Web Research",
  image_analysis: "Image Analysis",
  image_fraud: "Image Fraud Triage",
  stock_research: "Stock Research",
  software_engineer: "Software Engineer",
  image_generation: "Image Generation",
  document_analytics: "Document Analytics",
};

export const AGENT_COLORS: Record<string, string> = {
  chat: "bg-blue-500",
  sql: "bg-emerald-500",
  document: "bg-amber-500",
  rag: "bg-violet-500",
  rag_v2: "bg-indigo-600",
  web: "bg-rose-500",
  image_analysis: "bg-cyan-500",
  image_fraud: "bg-orange-500",
  stock_research: "bg-green-600",
  software_engineer: "bg-slate-600",
  image_generation: "bg-fuchsia-500",
  document_analytics: "bg-amber-600",
};
