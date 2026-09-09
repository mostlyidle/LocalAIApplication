import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { DocumentUploader } from "../DocumentUploader";

// Mock lucide-react icons to simple elements
vi.mock("lucide-react", () => ({
  Upload: (props: Record<string, unknown>) => <svg data-testid="upload-icon" {...props} />,
  FileUp: (props: Record<string, unknown>) => <svg data-testid="fileup-icon" {...props} />,
  X: (props: Record<string, unknown>) => <svg data-testid="x-icon" {...props} />,
}));

describe("DocumentUploader", () => {
  let onUpload: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    onUpload = vi.fn().mockResolvedValue({ id: "doc-1" });
  });

  it("renders the drop zone with instructions", () => {
    render(<DocumentUploader onUpload={onUpload} />);
    expect(screen.getByText(/Drop a file here or click to browse/i)).toBeInTheDocument();
    expect(screen.getByText(/PDF, DOCX, XLSX/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Select File/i })).toBeInTheDocument();
  });

  it("has a hidden file input", () => {
    render(<DocumentUploader onUpload={onUpload} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).toBeInTheDocument();
    expect(input.className).toContain("hidden");
  });

  it("calls onUpload when a valid file is selected", async () => {
    render(<DocumentUploader onUpload={onUpload} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["content"], "test.pdf", { type: "application/pdf" });

    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(onUpload).toHaveBeenCalledWith(file);
    });
  });

  it("shows error for oversized files", async () => {
    render(<DocumentUploader onUpload={onUpload} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;

    // Create a file larger than 50MB
    const bigFile = new File(["x"], "huge.pdf", { type: "application/pdf" });
    Object.defineProperty(bigFile, "size", { value: 60 * 1024 * 1024 });

    fireEvent.change(input, { target: { files: [bigFile] } });

    await waitFor(() => {
      expect(screen.getByText(/File too large/i)).toBeInTheDocument();
    });
    expect(onUpload).not.toHaveBeenCalled();
  });

  it("shows error for unsupported file types", async () => {
    render(<DocumentUploader onUpload={onUpload} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;

    const badFile = new File(["data"], "malware.exe", { type: "application/x-msdownload" });
    fireEvent.change(input, { target: { files: [badFile] } });

    await waitFor(() => {
      expect(screen.getByText(/Unsupported file type/i)).toBeInTheDocument();
    });
    expect(onUpload).not.toHaveBeenCalled();
  });

  it("shows 'Uploading...' during upload", async () => {
    // Make onUpload hang until we resolve it
    let resolveUpload: (v: unknown) => void;
    onUpload.mockReturnValue(new Promise((r) => { resolveUpload = r; }));

    render(<DocumentUploader onUpload={onUpload} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["content"], "doc.pdf", { type: "application/pdf" });

    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText(/Uploading.../i)).toBeInTheDocument();
    });

    // The select button should be disabled during upload
    expect(screen.getByRole("button", { name: /Select File/i })).toBeDisabled();

    // Resolve the upload
    resolveUpload!({ id: "doc-1" });

    await waitFor(() => {
      expect(screen.getByText(/Drop a file here/i)).toBeInTheDocument();
    });
  });

  it("shows upload error message", async () => {
    onUpload.mockRejectedValue(new Error("Server error"));

    render(<DocumentUploader onUpload={onUpload} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["content"], "doc.pdf", { type: "application/pdf" });

    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText(/Server error/i)).toBeInTheDocument();
    });
  });

  it("handles non-Error upload failures", async () => {
    onUpload.mockRejectedValue("string error");

    render(<DocumentUploader onUpload={onUpload} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["content"], "doc.pdf", { type: "application/pdf" });

    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText(/Upload failed/i)).toBeInTheDocument();
    });
  });

  it("handles drag and drop", async () => {
    render(<DocumentUploader onUpload={onUpload} />);
    const card = screen.getByText(/Drop a file here/i).closest("[class]")!;

    const file = new File(["content"], "test.csv", { type: "text/csv" });

    fireEvent.dragOver(card, { preventDefault: vi.fn() });
    fireEvent.drop(card, {
      preventDefault: vi.fn(),
      dataTransfer: { files: [file] },
    });

    await waitFor(() => {
      expect(onUpload).toHaveBeenCalledWith(file);
    });
  });

  it("clears error when a valid file is uploaded after error", async () => {
    render(<DocumentUploader onUpload={onUpload} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;

    // First: trigger an error
    const badFile = new File(["x"], "bad.exe", { type: "application/x-msdownload" });
    fireEvent.change(input, { target: { files: [badFile] } });

    await waitFor(() => {
      expect(screen.getByText(/Unsupported file type/i)).toBeInTheDocument();
    });

    // Then: upload a valid file — error should clear
    const goodFile = new File(["content"], "good.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [goodFile] } });

    await waitFor(() => {
      expect(screen.queryByText(/Unsupported file type/i)).not.toBeInTheDocument();
    });
  });

  it("resets file input value after selection", async () => {
    render(<DocumentUploader onUpload={onUpload} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["content"], "test.pdf", { type: "application/pdf" });

    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(onUpload).toHaveBeenCalled();
    });
    // Input value should be cleared so the same file can be re-selected
    expect(input.value).toBe("");
  });
});
