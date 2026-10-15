"use client";

import { useCallback, useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { Document } from "@/types/document";

export function useDocuments() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchDocuments = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.getDocuments();
      setDocuments(data.documents.map((doc) => ({
        id: doc.id,
        filename: doc.filename,
        format: doc.format,
        sizeBytes: doc.size_bytes,
        contentSha256: doc.content_sha256,
        status: doc.status,
        wordCount: 0,
        createdAt: doc.created_at,
        updatedAt: doc.created_at,
      })));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load documents");
    } finally {
      setIsLoading(false);
    }
  }, []);

  const upload = useCallback(async (file: File) => {
    setError(null);
    try {
      const result = await api.uploadDocument(file);
      await fetchDocuments();
      return result;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Upload failed";
      setError(msg);
      throw err;
    }
  }, [fetchDocuments]);

  const remove = useCallback(async (id: string) => {
    setError(null);
    try {
      await api.deleteDocument(id);
      setDocuments((prev) => prev.filter((d) => d.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  }, []);

  const analyze = useCallback(async (id: string, prompt?: string) => {
    setError(null);
    try {
      const result = await api.analyzeDocument(id, prompt);
      setDocuments((prev) => prev.map((doc) => doc.id === id ? {
        ...doc,
        status: "completed",
        pageCount: result.page_count ?? undefined,
        wordCount: result.word_count,
      } : doc));
      return result;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Analysis failed";
      setError(msg);
      throw err;
    }
  }, []);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  return { documents, isLoading, error, fetchDocuments, upload, remove, analyze };
}
