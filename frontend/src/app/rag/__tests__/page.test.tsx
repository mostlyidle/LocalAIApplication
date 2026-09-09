import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, describe, it, expect, beforeEach } from "vitest";
import RAGPage from "../page";

// Mock lucide-react
vi.mock("lucide-react", () => ({
  Search: (props: Record<string, unknown>) => <svg data-testid="search-icon" {...props} />,
  Trash2: (props: Record<string, unknown>) => <svg data-testid="trash-icon" {...props} />,
  Database: (props: Record<string, unknown>) => <svg data-testid="db-icon" {...props} />,
  Loader2: (props: Record<string, unknown>) => <svg data-testid="loader-icon" {...props} />,
  FileText: (props: Record<string, unknown>) => <svg data-testid="file-icon" {...props} />,
  Upload: (props: Record<string, unknown>) => <svg data-testid="upload-icon" {...props} />,
}));

// Mock the API module
vi.mock("@/lib/api", () => ({
  getRAGCollections: vi.fn(),
  searchRAG: vi.fn(),
  deleteRAGCollection: vi.fn(),
  getDocuments: vi.fn(),
  ingestRAG: vi.fn(),
}));

import * as api from "@/lib/api";

const mockGetCollections = api.getRAGCollections as ReturnType<typeof vi.fn>;
const mockSearchRAG = api.searchRAG as ReturnType<typeof vi.fn>;
const mockDeleteCollection = api.deleteRAGCollection as ReturnType<typeof vi.fn>;
const mockGetDocuments = api.getDocuments as ReturnType<typeof vi.fn>;
const mockIngestRAG = api.ingestRAG as ReturnType<typeof vi.fn>;

describe("RAG Page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetCollections.mockResolvedValue({
      collections: [
        { name: "documents", count: 10 },
        { name: "reports", count: 3 },
      ],
    });
    mockGetDocuments.mockResolvedValue({
      documents: [
        { id: "d1", filename: "report.pdf", format: "pdf", size_bytes: 10240, status: "completed" },
        { id: "d2", filename: "notes.md", format: "md", size_bytes: 2048, status: "completed" },
      ],
    });
  });

  it("renders the page title", async () => {
    await act(async () => {
      render(<RAGPage />);
    });
    expect(screen.getByText("RAG Search")).toBeInTheDocument();
  });

  it("renders search input and button", async () => {
    await act(async () => {
      render(<RAGPage />);
    });
    expect(screen.getByPlaceholderText(/Search your knowledge base/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Search/i })).toBeInTheDocument();
  });

  it("loads and displays collections on mount", async () => {
    await act(async () => {
      render(<RAGPage />);
    });

    await waitFor(() => {
      expect(screen.getByText("documents")).toBeInTheDocument();
      expect(screen.getByText("10 documents")).toBeInTheDocument();
      expect(screen.getByText("reports")).toBeInTheDocument();
      expect(screen.getByText("3 documents")).toBeInTheDocument();
    });
  });

  it("shows empty state when no collections", async () => {
    mockGetCollections.mockResolvedValue({ collections: [] });

    await act(async () => {
      render(<RAGPage />);
    });

    await waitFor(() => {
      expect(screen.getByText(/No collections yet/i)).toBeInTheDocument();
    });
  });

  it("handles collection loading error gracefully", async () => {
    mockGetCollections.mockRejectedValue(new Error("Network error"));

    await act(async () => {
      render(<RAGPage />);
    });

    // Should not crash; just show no collections
    await waitFor(() => {
      expect(screen.getByText(/No collections yet/i)).toBeInTheDocument();
    });
  });

  it("search button is disabled when input is empty", async () => {
    await act(async () => {
      render(<RAGPage />);
    });
    expect(screen.getByRole("button", { name: /Search/i })).toBeDisabled();
  });

  it("performs search and displays results", async () => {
    mockSearchRAG.mockResolvedValue({
      results: [
        {
          content: "Python is a versatile language.",
          score: 0.95,
          metadata: { source: "intro.pdf", page: 2 },
        },
        {
          content: "It supports async programming.",
          score: 0.82,
          metadata: { source: "guide.md" },
        },
      ],
    });

    await act(async () => {
      render(<RAGPage />);
    });

    const input = screen.getByPlaceholderText(/Search your knowledge base/i);
    await userEvent.type(input, "Python features");

    const searchBtn = screen.getByRole("button", { name: /Search/i });
    await userEvent.click(searchBtn);

    await waitFor(() => {
      expect(screen.getByText("Results")).toBeInTheDocument();
      expect(screen.getByText("2 found")).toBeInTheDocument();
      expect(screen.getByText("Python is a versatile language.")).toBeInTheDocument();
      expect(screen.getByText("intro.pdf")).toBeInTheDocument();
      expect(screen.getByText("p.2")).toBeInTheDocument();
      expect(screen.getByText("95.0%")).toBeInTheDocument();
      expect(screen.getByText("It supports async programming.")).toBeInTheDocument();
    });
  });

  it("shows error message when search fails", async () => {
    mockSearchRAG.mockRejectedValue(new Error("Search engine down"));

    await act(async () => {
      render(<RAGPage />);
    });

    const input = screen.getByPlaceholderText(/Search your knowledge base/i);
    await userEvent.type(input, "test query");

    await userEvent.click(screen.getByRole("button", { name: /Search/i }));

    await waitFor(() => {
      expect(screen.getByText("Search engine down")).toBeInTheDocument();
    });
  });

  it("shows no results message", async () => {
    mockSearchRAG.mockResolvedValue({ results: [] });

    await act(async () => {
      render(<RAGPage />);
    });

    const input = screen.getByPlaceholderText(/Search your knowledge base/i);
    await userEvent.type(input, "obscure query");

    await userEvent.click(screen.getByRole("button", { name: /Search/i }));

    await waitFor(() => {
      expect(screen.getByText(/No results found/i)).toBeInTheDocument();
    });
  });

  it("deletes a collection", async () => {
    mockDeleteCollection.mockResolvedValue({ deleted: true });

    await act(async () => {
      render(<RAGPage />);
    });

    await waitFor(() => {
      expect(screen.getByText("documents")).toBeInTheDocument();
    });

    // Find the delete button for the first collection
    const trashIcons = screen.getAllByTestId("trash-icon");
    const deleteBtn = trashIcons[0].closest("button")!;
    await userEvent.click(deleteBtn);

    await waitFor(() => {
      expect(mockDeleteCollection).toHaveBeenCalledWith("documents");
      expect(screen.queryByText("10 documents")).not.toBeInTheDocument();
    });
  });

  it("shows error when delete fails", async () => {
    mockDeleteCollection.mockRejectedValue(new Error("Delete failed"));

    await act(async () => {
      render(<RAGPage />);
    });

    await waitFor(() => {
      expect(screen.getByText("documents")).toBeInTheDocument();
    });

    const trashIcons = screen.getAllByTestId("trash-icon");
    await userEvent.click(trashIcons[0].closest("button")!);

    await waitFor(() => {
      expect(screen.getByText("Delete failed")).toBeInTheDocument();
    });
  });

  it("does not search with whitespace-only query", async () => {
    await act(async () => {
      render(<RAGPage />);
    });

    const input = screen.getByPlaceholderText(/Search your knowledge base/i);
    await userEvent.type(input, "   ");

    // Button should be disabled since trimmed query is empty
    expect(screen.getByRole("button", { name: /Search/i })).toBeDisabled();
  });

  // --- Ingest UI Tests ---

  it("renders Ingest Documents section with document list", async () => {
    await act(async () => {
      render(<RAGPage />);
    });

    await waitFor(() => {
      expect(screen.getByText("Ingest Documents")).toBeInTheDocument();
      expect(screen.getByText("report.pdf")).toBeInTheDocument();
      expect(screen.getByText("notes.md")).toBeInTheDocument();
    });
  });

  it("shows empty state when no documents are uploaded", async () => {
    mockGetDocuments.mockResolvedValue({ documents: [] });

    await act(async () => {
      render(<RAGPage />);
    });

    await waitFor(() => {
      expect(screen.getByText(/No documents uploaded yet/i)).toBeInTheDocument();
    });
  });

  it("shows Ingest button for each document", async () => {
    await act(async () => {
      render(<RAGPage />);
    });

    await waitFor(() => {
      const ingestButtons = screen.getAllByRole("button", { name: /Ingest/i });
      expect(ingestButtons).toHaveLength(2);
    });
  });

  it("calls ingestRAG with document id and collection when Ingest is clicked", async () => {
    mockIngestRAG.mockResolvedValue({ message: "ok", chunks: 5 });

    await act(async () => {
      render(<RAGPage />);
    });

    await waitFor(() => {
      expect(screen.getByText("report.pdf")).toBeInTheDocument();
    });

    const ingestButtons = screen.getAllByRole("button", { name: /Ingest/i });
    await userEvent.click(ingestButtons[0]);

    await waitFor(() => {
      expect(mockIngestRAG).toHaveBeenCalledWith("d1", "documents");
    });
  });

  it("shows error when ingest fails", async () => {
    mockIngestRAG.mockRejectedValue(new Error("Ingest failed"));

    await act(async () => {
      render(<RAGPage />);
    });

    await waitFor(() => {
      expect(screen.getByText("report.pdf")).toBeInTheDocument();
    });

    const ingestButtons = screen.getAllByRole("button", { name: /Ingest/i });
    await userEvent.click(ingestButtons[0]);

    await waitFor(() => {
      expect(screen.getByText("Ingest failed")).toBeInTheDocument();
    });
  });

  it("refreshes collections after successful ingest", async () => {
    mockIngestRAG.mockResolvedValue({ message: "ok", chunks: 5 });

    await act(async () => {
      render(<RAGPage />);
    });

    await waitFor(() => {
      expect(screen.getByText("report.pdf")).toBeInTheDocument();
    });

    // Update collections response for the reload
    mockGetCollections.mockResolvedValue({
      collections: [
        { name: "documents", count: 15 },
        { name: "reports", count: 3 },
      ],
    });

    const ingestButtons = screen.getAllByRole("button", { name: /Ingest/i });
    await userEvent.click(ingestButtons[0]);

    await waitFor(() => {
      // Collections should have been reloaded
      expect(mockGetCollections).toHaveBeenCalledTimes(2); // initial + after ingest
    });
  });

  it("handles document loading error gracefully", async () => {
    mockGetDocuments.mockRejectedValue(new Error("Network error"));

    await act(async () => {
      render(<RAGPage />);
    });

    // Should not crash; the ingest section should show no documents
    await waitFor(() => {
      expect(screen.getByText(/No documents uploaded yet/i)).toBeInTheDocument();
    });
  });
});
