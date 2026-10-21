const configuredApiBase = process.env.NEXT_PUBLIC_API_URL || "";
const isNativeDesktop =
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
export const API_BASE = isNativeDesktop ? configuredApiBase : "";
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
  document_redaction: "Document Redaction Agent",
  rag: "RAG Agent",
  rag_v2: "RAG Agent v2",
  web: "Web Research",
  image_analysis: "Image Analysis",
  image_fraud: "Image Fraud Triage",
  stock_research: "Stock Research",
  software_engineer: "Software Engineer",
  image_generation: "Image Generation",
  document_analytics: "Document Analytics",
  medical_lab_explainer: "Lab Report Explainer",
};

export const AGENT_COLORS: Record<string, string> = {
  chat: "bg-violet-soft text-violet-ink",
  sql: "bg-mint-soft text-mint-ink",
  document: "bg-peach-soft text-peach-ink",
  document_redaction: "bg-rose-soft text-rose-ink",
  rag: "bg-sky-soft text-sky-ink",
  rag_v2: "bg-sky-soft text-sky-ink",
  web: "bg-rose-soft text-rose-ink",
  image_analysis: "bg-sky-soft text-sky-ink",
  image_fraud: "bg-peach-soft text-peach-ink",
  stock_research: "bg-mint-soft text-mint-ink",
  software_engineer: "bg-muted text-muted-foreground",
  image_generation: "bg-violet-soft text-violet-ink",
  document_analytics: "bg-peach-soft text-peach-ink",
};
