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
  getRedactionReview: vi.fn(),
  downloadRedactionBatch: vi.fn(),
  exportRedactedDocument: vi.fn(),
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
    vi.mocked(api.downloadRedactionBatch).mockResolvedValue({
      blob: new Blob(["zip"]), filename: "redacted-documents.zip",
    });
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

  it("uploads supported documents selected from a folder", async () => {
    vi.mocked(api.uploadDocument)
      .mockResolvedValueOnce(uploaded)
      .mockResolvedValueOnce(secondUploaded);
    const firstFile = new File(["PDF content"], "first.pdf", { type: "application/pdf" });
    const secondFile = new File(["image content"], "second.png", { type: "image/png" });
    Object.defineProperty(firstFile, "webkitRelativePath", { value: "redactions/first.pdf" });
    Object.defineProperty(secondFile, "webkitRelativePath", { value: "redactions/second.png" });
    render(<RedactionPage />);

    fireEvent.change(screen.getByLabelText("Select folder of PDFs or images"), {
      target: { files: [firstFile, secondFile] },
    });

    await waitFor(() => expect(api.uploadDocument).toHaveBeenCalledTimes(2));
    expect(api.uploadDocument).toHaveBeenNthCalledWith(1, firstFile);
    expect(api.uploadDocument).toHaveBeenNthCalledWith(2, secondFile);
    expect(await screen.findByRole("checkbox", { name: uploaded.filename })).toBeChecked();
    expect(await screen.findByRole("checkbox", { name: secondUploaded.filename })).toBeChecked();
    expect(screen.getByLabelText("Select folder of PDFs or images")).toHaveAttribute(
      "webkitdirectory",
    );
  });

  it("recursively uploads supported files from a dropped folder", async () => {
    vi.mocked(api.uploadDocument)
      .mockResolvedValueOnce(uploaded)
      .mockResolvedValueOnce(secondUploaded);
    const rootFile = new File(["PDF content"], "first.pdf", { type: "application/pdf" });
    const nestedFile = new File(["image content"], "second.png", { type: "image/png" });
    const metadataFile = new File(["metadata"], ".DS_Store");
    const fileEntry = (name: string, file: File): FileSystemFileEntry => ({
      isFile: true,
      isDirectory: false,
      name,
      fullPath: `/redactions/${name}`,
      file: (callback) => callback(file),
    }) as FileSystemFileEntry;
    const rootFileEntry = fileEntry("first.pdf", rootFile);
    const metadataEntry = fileEntry(".DS_Store", metadataFile);
    const nestedFileEntry = fileEntry("second.png", nestedFile);
    const nestedDirectory = {
      isFile: false,
      isDirectory: true,
      name: "nested",
      fullPath: "/redactions/nested",
      createReader: () => {
        let read = false;
        return {
          readEntries: (callback: (entries: FileSystemEntry[]) => void) => {
            callback(read ? [] : [nestedFileEntry]);
            read = true;
          },
        };
      },
    } as FileSystemDirectoryEntry;
    const directoryEntry = {
      isFile: false,
      isDirectory: true,
      name: "redactions",
      fullPath: "/redactions",
      createReader: () => {
        let read = false;
        return {
          readEntries: (callback: (entries: FileSystemEntry[]) => void) => {
            callback(read ? [] : [rootFileEntry, metadataEntry, nestedDirectory]);
            read = true;
          },
        };
      },
    } as FileSystemDirectoryEntry;
    const item = { webkitGetAsEntry: () => directoryEntry } as unknown as DataTransferItem;
    render(<RedactionPage />);

    fireEvent.drop(screen.getByTestId("redaction-upload-dropzone"), {
      dataTransfer: { items: [item], files: [] },
    });

    await waitFor(() => expect(api.uploadDocument).toHaveBeenCalledTimes(2));
    expect(api.uploadDocument).toHaveBeenNthCalledWith(1, rootFile);
    expect(api.uploadDocument).toHaveBeenNthCalledWith(2, nestedFile);
    expect(await screen.findByRole("alert")).toHaveTextContent("Skipped 1 unsupported");
  });

  it("stops traversing a dropped folder after the batch limit", async () => {
    const fileEntries = Array.from({ length: 21 }, (_, index) => {
      const file = new File(["PDF content"], `document-${index}.pdf`, { type: "application/pdf" });
      return {
        isFile: true,
        isDirectory: false,
        name: file.name,
        fullPath: `/redactions/${file.name}`,
        file: (callback: (value: File) => void) => callback(file),
      } as FileSystemFileEntry;
    });
    const directoryEntry = {
      isFile: false,
      isDirectory: true,
      name: "redactions",
      fullPath: "/redactions",
      createReader: () => {
        let read = false;
        return {
          readEntries: (callback: (entries: FileSystemEntry[]) => void) => {
            callback(read ? [] : fileEntries);
            read = true;
          },
        };
      },
    } as FileSystemDirectoryEntry;
    const item = { webkitGetAsEntry: () => directoryEntry } as unknown as DataTransferItem;
    render(<RedactionPage />);

    fireEvent.drop(screen.getByTestId("redaction-upload-dropzone"), {
      dataTransfer: { items: [item], files: [] },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Folder contains more than 20 supported documents",
    );
    expect(api.uploadDocument).not.toHaveBeenCalled();
  });

  it("locks document selection while a dropped folder is being read", async () => {
    vi.mocked(api.getDocuments).mockResolvedValue({ documents: [existing] });
    const rootFile = new File(["PDF content"], "new.pdf", { type: "application/pdf" });
    const fileEntry = {
      isFile: true,
      isDirectory: false,
      name: rootFile.name,
      fullPath: `/redactions/${rootFile.name}`,
      file: (callback: (value: File) => void) => callback(rootFile),
    } as FileSystemFileEntry;
    let deliverEntries: ((entries: FileSystemEntry[]) => void) | undefined;
    let read = false;
    const directoryEntry = {
      isFile: false,
      isDirectory: true,
      name: "redactions",
      fullPath: "/redactions",
      createReader: () => ({
        readEntries: (callback: (entries: FileSystemEntry[]) => void) => {
          if (read) callback([]);
          else {
            deliverEntries = callback;
            read = true;
          }
        },
      }),
    } as FileSystemDirectoryEntry;
    const item = { webkitGetAsEntry: () => directoryEntry } as unknown as DataTransferItem;
    render(<RedactionPage />);
    const existingCheckbox = await screen.findByRole("checkbox", { name: existing.filename });
    fireEvent.click(existingCheckbox);

    fireEvent.drop(screen.getByTestId("redaction-upload-dropzone"), {
      dataTransfer: { items: [item], files: [] },
    });

    expect(await screen.findByText("Reading folder...")).toBeInTheDocument();
    expect(existingCheckbox).toBeDisabled();
    expect(screen.getByRole("button", { name: "Analyze 1 document" })).toBeDisabled();
    expect(deliverEntries).toBeDefined();
    deliverEntries?.([fileEntry]);

    await waitFor(() => expect(api.uploadDocument).toHaveBeenCalledWith(rootFile));
    expect(await screen.findByRole("checkbox", { name: uploaded.filename })).toBeChecked();
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

  it("rejects a job URL that does not belong to the selected batch", async () => {
    const job = {
      id: "other-job", document_id: existing.id, batch_id: "other-batch", status: "queued",
      page_count: 0, pages_processed: 0, review_revision: 0, approved_revision: null,
      clarification_question: null, error_message: null, warnings: [],
    };
    vi.mocked(api.getRedactionBatch).mockResolvedValue({
      id: "batch-1",
      jobs: [{ ...job, id: "batch-job", batch_id: "batch-1" }],
    });
    vi.mocked(api.getRedactionJob).mockResolvedValue(job);
    window.history.replaceState(null, "", "/redaction?job_id=other-job&batch_id=batch-1");
    render(<RedactionPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This redaction job does not belong to the selected batch.",
    );
    expect(screen.queryByText("Batch progress")).not.toBeInTheDocument();
  });

  it("enables batch ZIP download only for current exported reviews", async () => {
    const exportedJob = {
      id: "job-1", document_id: existing.id, batch_id: "batch-1", status: "exported",
      page_count: 1, pages_processed: 1, review_revision: 2, approved_revision: 2,
      clarification_question: null, error_message: null, warnings: [],
    };
    const secondExportedJob = {
      ...exportedJob, id: "job-2", document_id: "second-document",
    };
    vi.mocked(api.getDocuments).mockResolvedValue({
      documents: [existing, { ...existing, id: "second-document", filename: "second.pdf" }],
    });
    vi.mocked(api.getRedactionBatch).mockResolvedValue({
      id: "batch-1", jobs: [exportedJob, secondExportedJob],
    });
    vi.mocked(api.getRedactionJob).mockResolvedValue(exportedJob);
    vi.mocked(api.getRedactionReview).mockResolvedValue({
      job: exportedJob, findings: [], pages: [], failed_pages: [],
    });
    window.history.replaceState(null, "", "/redaction?job_id=job-1&batch_id=batch-1");
    render(<RedactionPage />);

    expect(await screen.findByText("Batch progress")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download redacted ZIP" })).toBeEnabled();
  });

  it("enables ZIP download after the last batch job is exported", async () => {
    const approvedJob = {
      id: "job-1", document_id: existing.id, batch_id: "batch-1", status: "approved",
      page_count: 1, pages_processed: 1, review_revision: 2, approved_revision: 2,
      clarification_question: null, error_message: null, warnings: [],
    };
    const exportedJob = {
      ...approvedJob, id: "job-2", document_id: "second-document", status: "exported",
      approved_revision: 1, review_revision: 1,
    };
    vi.mocked(api.getDocuments).mockResolvedValue({
      documents: [existing, { ...existing, id: "second-document", filename: "second.pdf" }],
    });
    vi.mocked(api.getRedactionBatch).mockResolvedValue({
      id: "batch-1", jobs: [approvedJob, exportedJob],
    });
    vi.mocked(api.getRedactionJob).mockResolvedValue(approvedJob);
    vi.mocked(api.getRedactionReview).mockResolvedValue({
      job: approvedJob, findings: [], pages: [], failed_pages: [],
    });
    vi.mocked(api.exportRedactedDocument).mockResolvedValue({
      ...approvedJob, status: "exported",
    });
    window.history.replaceState(null, "", "/redaction?job_id=job-1&batch_id=batch-1");
    render(<RedactionPage />);

    const downloadButton = await screen.findByRole("button", { name: "Download redacted ZIP" });
    expect(downloadButton).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Create redacted PDF" }));

    await waitFor(() => expect(downloadButton).toBeEnabled());
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
