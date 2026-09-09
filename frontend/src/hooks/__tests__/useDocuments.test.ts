import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mock @/lib/api
// ---------------------------------------------------------------------------

vi.mock("@/lib/api", () => ({
  getDocuments: vi.fn(),
  uploadDocument: vi.fn(),
  deleteDocument: vi.fn(),
  analyzeDocument: vi.fn(),
}));

import * as api from "@/lib/api";
import { useDocuments } from "../useDocuments";

const mockGetDocuments = api.getDocuments as ReturnType<typeof vi.fn>;
const mockUploadDocument = api.uploadDocument as ReturnType<typeof vi.fn>;
const mockDeleteDocument = api.deleteDocument as ReturnType<typeof vi.fn>;
const mockAnalyzeDocument = api.analyzeDocument as ReturnType<typeof vi.fn>;

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useDocuments", () => {
  const sampleDocs = [
    { id: "d1", filename: "a.pdf", format: "pdf", sizeBytes: 100, status: "completed", wordCount: 500, createdAt: "", updatedAt: "" },
    { id: "d2", filename: "b.csv", format: "csv", sizeBytes: 50, status: "completed", wordCount: 200, createdAt: "", updatedAt: "" },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    mockGetDocuments.mockResolvedValue({ documents: sampleDocs });
  });

  it("fetches documents on mount", async () => {
    const { result } = renderHook(() => useDocuments());

    // Initially loading
    expect(result.current.isLoading).toBe(true);

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.documents).toEqual(sampleDocs);
    expect(mockGetDocuments).toHaveBeenCalledTimes(1);
  });

  it("sets error when fetchDocuments fails", async () => {
    mockGetDocuments.mockRejectedValueOnce(new Error("Network error"));

    const { result } = renderHook(() => useDocuments());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.error).toBe("Network error");
    expect(result.current.documents).toEqual([]);
  });

  it("handles non-Error thrown from fetch gracefully", async () => {
    mockGetDocuments.mockRejectedValueOnce("string error");

    const { result } = renderHook(() => useDocuments());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.error).toBe("Failed to load documents");
  });

  it("upload calls uploadDocument and refetches", async () => {
    mockUploadDocument.mockResolvedValue({ id: "d3", filename: "c.txt" });
    // After upload, refetch returns updated list
    mockGetDocuments.mockResolvedValue({ documents: [...sampleDocs, { id: "d3", filename: "c.txt" }] });

    const { result } = renderHook(() => useDocuments());

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    const file = new File(["test"], "c.txt", { type: "text/plain" });
    let uploadResult: unknown;
    await act(async () => {
      uploadResult = await result.current.upload(file);
    });

    expect(mockUploadDocument).toHaveBeenCalledWith(file);
    expect(uploadResult).toEqual({ id: "d3", filename: "c.txt" });
    // Should have refetched
    expect(mockGetDocuments).toHaveBeenCalledTimes(2);
  });

  it("upload sets error and rethrows on failure", async () => {
    mockUploadDocument.mockRejectedValue(new Error("File too large"));

    const { result } = renderHook(() => useDocuments());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    let caught: Error | undefined;
    await act(async () => {
      try {
        await result.current.upload(new File(["x"], "big.pdf"));
      } catch (err) {
        caught = err as Error;
      }
    });

    expect(caught?.message).toBe("File too large");
    expect(result.current.error).toBe("File too large");
  });

  it("remove calls deleteDocument and removes from state", async () => {
    mockDeleteDocument.mockResolvedValue({ deleted: true });

    const { result } = renderHook(() => useDocuments());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.documents).toHaveLength(2);

    await act(async () => {
      await result.current.remove("d1");
    });

    expect(mockDeleteDocument).toHaveBeenCalledWith("d1");
    expect(result.current.documents).toHaveLength(1);
    expect(result.current.documents[0].id).toBe("d2");
  });

  it("remove sets error on failure", async () => {
    mockDeleteDocument.mockRejectedValue(new Error("Not found"));

    const { result } = renderHook(() => useDocuments());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.remove("d99");
    });

    expect(result.current.error).toBe("Not found");
  });

  it("analyze calls analyzeDocument and returns result", async () => {
    mockAnalyzeDocument.mockResolvedValue({ document_id: "d1", analysis: "Summary of document" });

    const { result } = renderHook(() => useDocuments());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    let analysis: unknown;
    await act(async () => {
      analysis = await result.current.analyze("d1", "summarize this");
    });

    expect(mockAnalyzeDocument).toHaveBeenCalledWith("d1", "summarize this");
    expect(analysis).toEqual({ document_id: "d1", analysis: "Summary of document" });
  });

  it("analyze sets error and rethrows on failure", async () => {
    mockAnalyzeDocument.mockRejectedValue(new Error("LLM error"));

    const { result } = renderHook(() => useDocuments());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    let caught: Error | undefined;
    await act(async () => {
      try {
        await result.current.analyze("d1");
      } catch (err) {
        caught = err as Error;
      }
    });

    expect(caught?.message).toBe("LLM error");
    expect(result.current.error).toBe("LLM error");
  });
});
