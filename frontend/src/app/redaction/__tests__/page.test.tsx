import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RedactionPage from "../page";
import * as api from "@/lib/api";
import { MAX_FILE_SIZE } from "@/lib/constants";

vi.mock("@/lib/api", () => ({
  getDocuments: vi.fn(),
  uploadDocument: vi.fn(),
  createRedactionBatch: vi.fn(),
  getRedactionBatch: vi.fn(),
  getRedactionJob: vi.fn(),
}));

const uploaded = { id: "uploaded-pdf", filename: "new-source.pdf", format: "pdf" };
const secondUploaded = { id: "uploaded-pdf-2", filename: "second-source.pdf", format: "pdf" };
const existing = {
  id: "existing-pdf",
  filename: "existing.pdf",
  format: "pdf",
  size_bytes: 100,
  status: "pending" as const,
  created_at: "2026-10-19T00:00:00Z",
};

describe("RedactionPage uploads", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    window.history.replaceState(null, "", "/redaction");
    vi.mocked(api.getDocuments).mockResolvedValue({ documents: [] });
    vi.mocked(api.uploadDocument).mockResolvedValue(uploaded);
    vi.mocked(api.getRedactionBatch).mockResolvedValue({ id: "batch-1", jobs: [] });
  });

  it("selects a new upload and uses it for redaction", async () => {
    vi.mocked(api.uploadDocument)
      .mockResolvedValueOnce(uploaded)
      .mockResolvedValueOnce(secondUploaded);
    vi.mocked(api.createRedactionBatch).mockResolvedValue({
      id: "batch-1",
      jobs: [{
        id: "new-job",
        document_id: uploaded.id,
        batch_id: "batch-1",
        status: "queued",
        page_count: 0,
        pages_processed: 0,
        review_revision: 0,
        approved_revision: null,
        clarification_question: null,
        error_message: null,
        warnings: [],
      }],
    });
    render(<RedactionPage />);
    const files = [
      new File(["PDF content"], uploaded.filename, { type: "application/pdf" }),
      new File(["PDF content 2"], secondUploaded.filename, { type: "application/pdf" }),
    ];

    fireEvent.change(screen.getByLabelText("Upload PDFs or images"), {
      target: { files },
    });

    await waitFor(() => expect(screen.getByRole("checkbox", { name: uploaded.filename })).toBeChecked());
    await waitFor(() => expect(screen.getByRole("checkbox", { name: secondUploaded.filename })).toBeChecked());
    expect(api.uploadDocument).toHaveBeenNthCalledWith(1, files[0]);
    expect(api.uploadDocument).toHaveBeenNthCalledWith(2, files[1]);
    fireEvent.click(screen.getByRole("button", { name: "Analyze 2 documents" }));
    await waitFor(() => expect(api.createRedactionBatch).toHaveBeenCalledWith(
      expect.objectContaining({ document_ids: [uploaded.id, secondUploaded.id] }),
    ));
  });

  it("shows batch progress and opens another document job", async () => {
    const firstJob = {
      id: "job-1", document_id: existing.id, batch_id: "batch-1", status: "queued",
      page_count: 0, pages_processed: 0, review_revision: 0, approved_revision: null,
      clarification_question: null, error_message: null, warnings: [],
    };
    const secondJob = {
      ...firstJob, id: "job-2", document_id: "second-document",
    };
    vi.mocked(api.getDocuments).mockResolvedValue({
      documents: [existing, { ...existing, id: "second-document", filename: "second.pdf" }],
    });
    vi.mocked(api.getRedactionBatch).mockResolvedValue({ id: "batch-1", jobs: [firstJob, secondJob] });
    vi.mocked(api.getRedactionJob)
      .mockResolvedValueOnce(firstJob)
      .mockResolvedValueOnce({ ...secondJob, status: "processing" });
    window.history.replaceState(null, "", "/redaction?job_id=job-1&batch_id=batch-1");
    render(<RedactionPage />);

    expect(await screen.findByText("Batch progress")).toBeInTheDocument();
    expect(await screen.findByText("second.pdf")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open" }));

    await waitFor(() => expect(api.getRedactionJob).toHaveBeenCalledWith("job-2"));
    expect(await screen.findByRole("button", { name: "Currently reviewing" })).toBeInTheDocument();
  });

  it.each(["unsupported", "oversized"])("rejects %s files before upload", async (kind) => {
    render(<RedactionPage />);
    const file = new File(["content"], kind === "unsupported" ? "report.docx" : "huge.pdf");
    if (kind === "oversized") Object.defineProperty(file, "size", { value: MAX_FILE_SIZE + 1 });

    fireEvent.change(screen.getByLabelText("Upload PDFs or images"), {
      target: { files: [file] },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      kind === "unsupported" ? "Unsupported file" : "File too large",
    );
    expect(api.uploadDocument).not.toHaveBeenCalled();
  });

  it("keeps the previous source selected when upload fails", async () => {
    vi.mocked(api.getDocuments).mockResolvedValue({ documents: [existing] });
    vi.mocked(api.uploadDocument).mockRejectedValue(new Error("Upload failed. Try again."));
    render(<RedactionPage />);
    const existingSource = await screen.findByRole("checkbox", { name: existing.filename });
    fireEvent.click(existingSource);

    fireEvent.change(screen.getByLabelText("Upload PDFs or images"), {
      target: { files: [new File(["content"], "retry.pdf")] },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Upload failed. Try again.");
    expect(existingSource).toBeChecked();
    expect(screen.getByRole("button", { name: "Analyze 1 document" })).toBeEnabled();
  });

  it("blocks source changes and analysis until the upload finishes", async () => {
    let finishUpload: () => void = () => { throw new Error("Upload has not started"); };
    vi.mocked(api.uploadDocument).mockImplementation(() => new Promise((resolve) => {
      finishUpload = () => resolve(uploaded);
    }));
    vi.mocked(api.getDocuments).mockResolvedValue({ documents: [existing] });
    render(<RedactionPage />);
    fireEvent.change(screen.getByLabelText("Upload PDFs or images"), {
      target: { files: [new File(["content"], uploaded.filename)] },
    });

    expect(screen.getByRole("status")).toHaveTextContent("Uploading...");
    expect(await screen.findByRole("checkbox", { name: existing.filename })).toBeDisabled();
    expect(screen.getByLabelText("Upload PDFs or images")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Analyze 0 documents" })).toBeDisabled();
    await act(async () => finishUpload());
    await waitFor(() => expect(screen.getByRole("button", { name: "Analyze 1 document" })).toBeEnabled());
  });

  it("keeps a new upload when the initial document list arrives later", async () => {
    let finishLoading: () => void = () => { throw new Error("Loading has not started"); };
    vi.mocked(api.getDocuments).mockImplementation(() => new Promise((resolve) => {
      finishLoading = () => resolve({ documents: [existing] });
    }));
    render(<RedactionPage />);
    fireEvent.change(screen.getByLabelText("Upload PDFs or images"), {
      target: { files: [new File(["content"], uploaded.filename)] },
    });
    await waitFor(() => expect(screen.getByRole("checkbox", { name: uploaded.filename })).toBeChecked());

    finishLoading();

    expect(await screen.findByRole("checkbox", { name: existing.filename })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: uploaded.filename })).toBeChecked();
  });
});
