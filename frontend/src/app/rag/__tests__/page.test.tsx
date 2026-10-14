import { render, screen, waitFor, act } from "@testing-library/react";
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
  ChevronDownIcon: (props: Record<string, unknown>) => <svg {...props} />,
  ChevronUpIcon: (props: Record<string, unknown>) => <svg {...props} />,
  CheckIcon: (props: Record<string, unknown>) => <svg {...props} />,
}));

// Mock the API module
vi.mock("@/lib/api", () => ({
  getRAGCollections: vi.fn(),
  getRAGContainers: vi.fn(),
  searchRAG: vi.fn(),
  deleteRAGCollection: vi.fn(),
  getDocuments: vi.fn(),
  ingestRAG: vi.fn(),
  getRAGContainerFiles: vi.fn(),
  createRAGContainer: vi.fn(),
  uploadRAGContainerFiles: vi.fn(),
  loadRAGContainer: vi.fn(),
  retryRAGContainerFile: vi.fn(),
  deleteRAGContainerFile: vi.fn(),
  deleteRAGContainer: vi.fn(),
}));

import * as api from "@/lib/api";

const mockGetCollections = api.getRAGCollections as ReturnType<typeof vi.fn>;
const mockGetContainers = api.getRAGContainers as ReturnType<typeof vi.fn>;
const mockSearchRAG = api.searchRAG as ReturnType<typeof vi.fn>;
const mockDeleteCollection = api.deleteRAGCollection as ReturnType<typeof vi.fn>;
const mockGetDocuments = api.getDocuments as ReturnType<typeof vi.fn>;
const mockIngestRAG = api.ingestRAG as ReturnType<typeof vi.fn>;

async function selectOption(label: string, option: string) {
  await userEvent.click(await screen.findByRole("combobox", { name: label }));
  await userEvent.click(await screen.findByRole("option", { name: option }));
}

describe("RAG Page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetCollections.mockResolvedValue({
      collections: [
        { name: "documents", count: 10 },
        { name: "reports", count: 3 },
      ],
    });
    mockGetContainers.mockResolvedValue([]);
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

    await userEvent.click(await screen.findByRole("combobox", { name: "Search index" }));
    expect(screen.getByRole("option", { name: "documents" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("option", { name: "reports", hidden: true })).toBeInTheDocument();
    expect(screen.getByText("10 chunks")).toBeInTheDocument();
    expect(screen.getByText("3 chunks")).toBeInTheDocument();
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

  it("shows a retryable collection loading error instead of an empty state", async () => {
    mockGetCollections
      .mockRejectedValueOnce(new Error("Network error"))
      .mockResolvedValueOnce({ collections: [{ name: "reports", count: 2 }] });

    await act(async () => {
      render(<RAGPage />);
    });

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Could not load collections: Network error");
    });
    expect(screen.queryByText(/No collections yet/i)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await userEvent.click(await screen.findByRole("combobox", { name: "Search index" }));
    await waitFor(() => {
      expect(screen.getByRole("option", { name: "reports" })).toBeInTheDocument();
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows a retryable container loading error", async () => {
    mockGetContainers
      .mockRejectedValueOnce(new Error("Container service unavailable"))
      .mockResolvedValueOnce([]);

    await act(async () => {
      render(<RAGPage />);
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load RAG containers: Container service unavailable",
    );
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
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
          score_type: "cosine",
          metadata: { source: "intro.pdf", page: 2 },
        },
        {
          content: "It supports async programming.",
          score: 0.82,
          score_type: "cosine",
          metadata: { source: "guide.md" },
        },
      ],
    });

    await act(async () => {
      render(<RAGPage />);
    });

    const input = screen.getByPlaceholderText(/Search your knowledge base/i);
    await selectOption("Search index", "documents");
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

  it("uses the selected retrieval profile and labels RRF scores as rankings", async () => {
    mockSearchRAG.mockResolvedValue({
      results: [{
        content: "A retrieved passage.",
        score: 0.0328,
        score_type: "rrf",
        metadata: { source: "report.pdf" },
      }],
    });

    await act(async () => {
      render(<RAGPage />);
    });
    await selectOption("Search index", "documents");
    await selectOption("Retrieval profile", "Hybrid + query rewrites");
    await userEvent.type(screen.getByPlaceholderText(/Search your knowledge base/i), "revenue");
    await userEvent.click(screen.getByRole("button", { name: /Search/i }));

    await waitFor(() => {
      expect(mockSearchRAG).toHaveBeenCalledWith("revenue", "documents", undefined, "rag_v2");
      expect(screen.getByText("RRF 0.0328")).toBeInTheDocument();
    });
  });

  it("shows error message when search fails", async () => {
    mockSearchRAG.mockRejectedValue(new Error("Search engine down"));

    await act(async () => {
      render(<RAGPage />);
    });

    const input = screen.getByPlaceholderText(/Search your knowledge base/i);
    await selectOption("Search index", "documents");
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
    await selectOption("Search index", "documents");
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

    await userEvent.click(await screen.findByRole("combobox", { name: "Search index" }));
    expect(screen.getByRole("option", { name: "documents" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await userEvent.type(screen.getByPlaceholderText(/Search your knowledge base/i), "search");

    // Find the delete button for the first collection
    const trashIcons = screen.getAllByTestId("trash-icon");
    const deleteBtn = trashIcons[0].closest("button")!;
    await userEvent.click(deleteBtn);

    await waitFor(() => {
      expect(mockDeleteCollection).toHaveBeenCalledWith("documents");
      expect(screen.queryByText("10 chunks")).not.toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /Search/i })).toBeDisabled();
  });

  it("shows error when delete fails", async () => {
    mockDeleteCollection.mockRejectedValue(new Error("Delete failed"));

    await act(async () => {
      render(<RAGPage />);
    });

    await userEvent.click(await screen.findByRole("combobox", { name: "Search index" }));
    expect(screen.getByRole("option", { name: "documents" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");

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

  it("shows a retryable document loading error instead of an empty state", async () => {
    mockGetDocuments
      .mockRejectedValueOnce(new Error("Network error"))
      .mockResolvedValueOnce({ documents: [] });

    await act(async () => {
      render(<RAGPage />);
    });

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Could not load documents: Network error");
    });
    expect(screen.queryByText(/No documents uploaded yet/i)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => {
      expect(screen.getByText(/No documents uploaded yet/i)).toBeInTheDocument();
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
