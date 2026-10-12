export * from "./chat";
export * from "./document";
export * from "./sql";

export interface HealthStatus {
  status: string;
  ollama: { status: string; models?: string[] };
  qdrant: { status: string };
  database: { status: string };
}

export interface RAGCollection {
  name: string;
  count: number;
}

export interface RAGSearchResult {
  content: string;
  score: number;
  metadata: Record<string, unknown>;
}

export interface RAGSearchResponse {
  results: RAGSearchResult[];
  query: string;
  collection: string;
}

export interface ToolInfo {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
}
