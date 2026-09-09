export interface Document {
  id: string;
  filename: string;
  format: string;
  sizeBytes: number;
  status: "pending" | "processing" | "completed" | "failed";
  pageCount?: number;
  wordCount: number;
  errorMessage?: string;
  createdAt: string;
  updatedAt: string;
}

export interface DocumentAnalysis {
  document_id: string;
  analysis: string;
  tables?: Record<string, unknown>[];
  metadata?: Record<string, unknown>;
}

export interface UploadResponse {
  id: string;
  filename: string;
  format: string;
  size_bytes: number;
  status: string;
}
