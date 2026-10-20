import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RedactionPage from "../page";
import * as api from "@/lib/api";
import { MAX_FILE_SIZE } from "@/lib/constants";

vi.mock("@/lib/api", () => ({
  getDocuments: vi.fn(),
  uploadDocument: vi.fn(),
  createRedactionJob: vi.fn(),
}));

const uploaded = { id: "uploaded-pdf", filename: "new-source.pdf", format: "pdf" };
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
  });

  it("selects a new upload and uses it for redaction", async () => {
    vi.mocked(api.createRedactionJob).mockResolvedValue({
      id: "new-job",
      document_id: uploaded.id,
      status: "queued",
      page_count: 0,
      pages_processed: 0,
      review_revision: 0,
      approved_revision: null,
      clarification_question: null,
      error_message: null,
      warnings: [],
    });
    render(<RedactionPage />);
    const file = new File(["PDF content"], uploaded.filename, { type: "application/pdf" });

    fireEvent.change(screen.getByLabelText("Upload a PDF or image"), {
      target: { files: [file] },
    });

    await waitFor(() => expect(screen.getByRole("combobox")).toHaveValue(uploaded.id));
    expect(api.uploadDocument).toHaveBeenCalledWith(file);
    fireEvent.click(screen.getByRole("button", { name: "Analyze document" }));
    await waitFor(() => expect(api.createRedactionJob).toHaveBeenCalledWith(
      expect.objectContaining({ document_id: uploaded.id }),
    ));
  });

  it.each(["unsupported", "oversized"])("rejects %s files before upload", async (kind) => {
    render(<RedactionPage />);
    const file = new File(["content"], kind === "unsupported" ? "report.docx" : "huge.pdf");
    if (kind === "oversized") Object.defineProperty(file, "size", { value: MAX_FILE_SIZE + 1 });

    fireEvent.change(screen.getByLabelText("Upload a PDF or image"), {
      target: { files: [file] },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      kind === "unsupported" ? "Choose a PDF or supported image" : "File too large",
    );
    expect(api.uploadDocument).not.toHaveBeenCalled();
  });

  it("keeps the previous source selected when upload fails", async () => {
    vi.mocked(api.getDocuments).mockResolvedValue({ documents: [existing] });
    vi.mocked(api.uploadDocument).mockRejectedValue(new Error("Upload failed. Try again."));
    render(<RedactionPage />);
    await screen.findByRole("option", { name: existing.filename });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: existing.id } });

    fireEvent.change(screen.getByLabelText("Upload a PDF or image"), {
      target: { files: [new File(["content"], "retry.pdf")] },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Upload failed. Try again.");
    expect(screen.getByRole("combobox")).toHaveValue(existing.id);
    expect(screen.getByRole("button", { name: "Analyze document" })).toBeEnabled();
  });

  it("blocks source changes and analysis until the upload finishes", async () => {
    let finishUpload: () => void = () => { throw new Error("Upload has not started"); };
    vi.mocked(api.uploadDocument).mockImplementation(() => new Promise((resolve) => {
      finishUpload = () => resolve(uploaded);
    }));
    render(<RedactionPage />);
    fireEvent.change(screen.getByLabelText("Upload a PDF or image"), {
      target: { files: [new File(["content"], uploaded.filename)] },
    });

    expect(screen.getByRole("status")).toHaveTextContent("Uploading...");
    expect(screen.getByRole("combobox")).toBeDisabled();
    expect(screen.getByLabelText("Upload a PDF or image")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Analyze document" })).toBeDisabled();
    finishUpload();
    await waitFor(() => expect(screen.getByRole("button", { name: "Analyze document" })).toBeEnabled());
  });

  it("keeps a new upload when the initial document list arrives later", async () => {
    let finishLoading: () => void = () => { throw new Error("Loading has not started"); };
    vi.mocked(api.getDocuments).mockImplementation(() => new Promise((resolve) => {
      finishLoading = () => resolve({ documents: [existing] });
    }));
    render(<RedactionPage />);
    fireEvent.change(screen.getByLabelText("Upload a PDF or image"), {
      target: { files: [new File(["content"], uploaded.filename)] },
    });
    await waitFor(() => expect(screen.getByRole("combobox")).toHaveValue(uploaded.id));

    finishLoading();

    await screen.findByRole("option", { name: existing.filename });
    expect(screen.getByRole("combobox")).toHaveValue(uploaded.id);
    expect(screen.getByRole("option", { name: uploaded.filename })).toBeInTheDocument();
  });
});
