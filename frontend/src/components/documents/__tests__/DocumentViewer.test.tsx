import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import type { ComponentProps } from "react";
import userEvent from "@testing-library/user-event";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { DocumentViewer } from "../DocumentViewer";
import type { Document } from "@/types/document";
import * as api from "@/lib/api";

// Mock lucide-react icons
vi.mock("lucide-react", () => ({
  FileText: (props: Record<string, unknown>) => <svg data-testid="file-icon" {...props} />,
  Trash2: (props: Record<string, unknown>) => <svg data-testid="trash-icon" {...props} />,
  Search: (props: Record<string, unknown>) => <svg data-testid="search-icon" {...props} />,
  Database: (props: Record<string, unknown>) => <svg data-testid="database-icon" {...props} />,
  XIcon: (props: Record<string, unknown>) => <svg data-testid="close-icon" {...props} />,
  Loader2: (props: Record<string, unknown>) => <svg data-testid="loader-icon" {...props} />,
  ChevronDownIcon: (props: Record<string, unknown>) => <svg {...props} />,
  ChevronUpIcon: (props: Record<string, unknown>) => <svg {...props} />,
  CheckIcon: (props: Record<string, unknown>) => <svg {...props} />,
}));

const baseDoc: Document = {
  id: "doc-1",
  filename: "report.pdf",
  format: "pdf",
  sizeBytes: 102400, // 100 KB
  status: "completed",
  pageCount: 5,
  wordCount: 1500,
  createdAt: "2025-01-01T00:00:00Z",
  updatedAt: "2025-01-01T00:00:00Z",
};

describe("DocumentViewer", () => {
  let onDelete: ReturnType<typeof vi.fn<ComponentProps<typeof DocumentViewer>["onDelete"]>>;
  let onAnalyze: ReturnType<typeof vi.fn<ComponentProps<typeof DocumentViewer>["onAnalyze"]>>;

  beforeEach(() => {
    onDelete = vi.fn();
    onAnalyze = vi.fn().mockResolvedValue({
      text: "Great report!",
      tables: [],
      metadata: {},
      page_count: 5,
      word_count: 1500,
    });
  });

  it("renders document filename and metadata", () => {
    render(
      <DocumentViewer document={baseDoc} onDelete={onDelete} onAnalyze={onAnalyze} />
    );
    expect(screen.getByText("report.pdf")).toBeInTheDocument();
    expect(screen.getByText("pdf")).toBeInTheDocument();
    expect(screen.getByText("100.0 KB")).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
    expect(screen.getByText("5 pages")).toBeInTheDocument();
    expect(screen.getByText("1,500 words")).toBeInTheDocument();
  });

  it("displays file size in bytes for tiny files", () => {
    const tinyDoc = { ...baseDoc, sizeBytes: 512 };
    render(
      <DocumentViewer document={tinyDoc} onDelete={onDelete} onAnalyze={onAnalyze} />
    );
    expect(screen.getByText("512 B")).toBeInTheDocument();
  });

  it("displays file size in MB for large files", () => {
    const largeDoc = { ...baseDoc, sizeBytes: 5 * 1024 * 1024 };
    render(
      <DocumentViewer document={largeDoc} onDelete={onDelete} onAnalyze={onAnalyze} />
    );
    expect(screen.getByText("5.0 MB")).toBeInTheDocument();
  });

  it("calls onDelete with the correct id", async () => {
    render(
      <DocumentViewer document={baseDoc} onDelete={onDelete} onAnalyze={onAnalyze} />
    );
    // Find the delete button (ghost button with trash icon)
    const deleteBtn = screen.getByTestId("trash-icon").closest("button")!;
    await userEvent.click(deleteBtn);
    expect(onDelete).toHaveBeenCalledWith("doc-1");
  });

  it("calls onAnalyze and displays result", async () => {
    render(
      <DocumentViewer document={baseDoc} onDelete={onDelete} onAnalyze={onAnalyze} />
    );
    const analyzeBtn = screen.getByRole("button", { name: /Analyze/i });
    await userEvent.click(analyzeBtn);

    await waitFor(() => {
      expect(onAnalyze).toHaveBeenCalledWith("doc-1", undefined);
    });
    await waitFor(() => {
      expect(screen.getByText("Great report!")).toBeInTheDocument();
    });
  });

  it("displays the answer to a document question separately from extracted text", async () => {
    onAnalyze.mockResolvedValueOnce({
      text: "Revenue was 42 million.",
      answer: "42 million.",
      tables: [],
      metadata: {},
      word_count: 4,
    });
    render(
      <DocumentViewer document={baseDoc} onDelete={onDelete} onAnalyze={onAnalyze} />
    );
    await userEvent.type(screen.getByRole("textbox", { name: /Question about/ }), "What was revenue?");
    await userEvent.click(screen.getByRole("button", { name: /Analyze/i }));

    expect(await screen.findByText("42 million.")).toBeInTheDocument();
    expect(screen.getByText("Revenue was 42 million.")).toBeInTheDocument();
  });

  it("sends custom prompt to onAnalyze", async () => {
    render(
      <DocumentViewer document={baseDoc} onDelete={onDelete} onAnalyze={onAnalyze} />
    );
    const textarea = screen.getByRole("textbox", { name: /Question about/ });
    await userEvent.type(textarea, "Summarize findings");

    const analyzeBtn = screen.getByRole("button", { name: /Analyze/i });
    await userEvent.click(analyzeBtn);

    await waitFor(() => {
      expect(onAnalyze).toHaveBeenCalledWith("doc-1", "Summarize findings");
    });
  });

  it("allows newly uploaded documents to be analyzed", () => {
    const pendingDoc = { ...baseDoc, status: "pending" as const };
    render(
      <DocumentViewer document={pendingDoc} onDelete={onDelete} onAnalyze={onAnalyze} />
    );
    expect(screen.getByRole("button", { name: /Analyze/i })).not.toBeDisabled();
  });

  it("queues an existing document in the selected private container", async () => {
    vi.spyOn(api, "getRAGContainers").mockResolvedValue([
      {
        name: "container_research",
        display_name: "Research",
        file_count: 0,
        indexed_file_count: 0,
        staged_file_count: 0,
        queued_file_count: 0,
        processing_file_count: 0,
        failed_file_count: 0,
        chunk_count: 0,
      },
    ]);
    const queueDocument = vi.spyOn(api, "queueDocumentInRAGContainer").mockResolvedValue({
      id: "file-1",
      relative_path: "report.pdf",
      status: "queued",
      chunk_count: 0,
      size_bytes: baseDoc.sizeBytes,
      last_error: null,
    });
    const user = userEvent.setup();
    render(
      <DocumentViewer document={baseDoc} onDelete={onDelete} onAnalyze={onAnalyze} />
    );

    await user.click(screen.getByRole("button", { name: /Add to index/i }));
    const containerSelect = await screen.findByRole("combobox", { name: "Target container" });
    containerSelect.focus();
    fireEvent.keyDown(containerSelect, { key: "ArrowDown" });
    const containerOption = await screen.findByRole("option", { name: /Research/ });
    fireEvent.keyDown(containerOption, { key: "Enter" });
    await user.click(screen.getByRole("button", { name: /Add to container/i }));

    await waitFor(() => {
      expect(queueDocument).toHaveBeenCalledWith("container_research", "doc-1");
    });
    await waitFor(() => expect(screen.getByRole("button", { name: /Add to index/i })).toHaveFocus());
  });

  it("returns focus to Add to index when its dialog is dismissed", async () => {
    vi.spyOn(api, "getRAGContainers").mockResolvedValue([]);
    const user = userEvent.setup();
    render(<DocumentViewer document={baseDoc} onDelete={onDelete} onAnalyze={onAnalyze} />);
    const trigger = screen.getByRole("button", { name: /Add to index/i });
    await user.click(trigger);
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("disables Analyze button during analysis", async () => {
    let resolveAnalyze: (v: Awaited<ReturnType<ComponentProps<typeof DocumentViewer>["onAnalyze"]>>) => void;
    onAnalyze.mockReturnValue(new Promise((r) => { resolveAnalyze = r; }));

    render(
      <DocumentViewer document={baseDoc} onDelete={onDelete} onAnalyze={onAnalyze} />
    );
    const analyzeBtn = screen.getByRole("button", { name: /Analyze/i });
    await userEvent.click(analyzeBtn);

    await waitFor(() => {
      expect(analyzeBtn).toBeDisabled();
    });

    resolveAnalyze!({ text: "Done", tables: [], metadata: {}, word_count: 0 });
    await waitFor(() => {
      expect(analyzeBtn).not.toBeDisabled();
    });
  });

  it("shows failure message when analysis fails", async () => {
    onAnalyze.mockRejectedValue(new Error("API error"));

    render(
      <DocumentViewer document={baseDoc} onDelete={onDelete} onAnalyze={onAnalyze} />
    );
    const analyzeBtn = screen.getByRole("button", { name: /Analyze/i });
    await userEvent.click(analyzeBtn);

    await waitFor(() => {
      expect(screen.getByText(/Analysis failed/i)).toBeInTheDocument();
    });
  });

  it("shows error message for failed documents", () => {
    const failedDoc: Document = {
      ...baseDoc,
      status: "failed",
      errorMessage: "Corrupted file",
    };
    render(
      <DocumentViewer document={failedDoc} onDelete={onDelete} onAnalyze={onAnalyze} />
    );
    expect(screen.getByText("Corrupted file")).toBeInTheDocument();
  });

  it("hides page count when not provided", () => {
    const noPagesDoc = { ...baseDoc, pageCount: undefined };
    render(
      <DocumentViewer document={noPagesDoc} onDelete={onDelete} onAnalyze={onAnalyze} />
    );
    expect(screen.queryByText(/pages/i)).not.toBeInTheDocument();
  });

  it("hides word count when zero", () => {
    const noWordsDoc = { ...baseDoc, wordCount: 0 };
    render(
      <DocumentViewer document={noWordsDoc} onDelete={onDelete} onAnalyze={onAnalyze} />
    );
    expect(screen.queryByText(/words/i)).not.toBeInTheDocument();
  });
});
