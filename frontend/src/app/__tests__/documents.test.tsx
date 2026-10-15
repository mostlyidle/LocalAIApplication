import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// Mock lucide-react
vi.mock("lucide-react", () => ({
  FileText: (props: Record<string, unknown>) => <span {...props} />,
  FileUp: (props: Record<string, unknown>) => <span {...props} />,
}));

// Mock UI components
vi.mock("@/components/ui/skeleton", () => ({
  Skeleton: (props: Record<string, unknown>) => <div data-testid="skeleton" {...props} />,
}));

// Mock child components
vi.mock("@/components/documents/DocumentUploader", () => ({
  DocumentUploader: () => <div data-testid="doc-uploader">Uploader</div>,
}));
vi.mock("@/components/documents/DocumentViewer", () => ({
  DocumentViewer: ({ document, duplicateCount }: {
    document: { id: string; filename: string };
    duplicateCount?: number;
  }) => (
    <div data-testid="doc-viewer">
      {document.filename}
      {duplicateCount && duplicateCount > 1 ? " · " + duplicateCount + " identical uploads" : ""}
    </div>
  ),
}));

const mockUseDocuments = vi.fn();
vi.mock("@/hooks/useDocuments", () => ({
  useDocuments: () => mockUseDocuments(),
}));

import DocumentsPage from "@/app/documents/page";

describe("DocumentsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseDocuments.mockReturnValue({
      documents: [],
      isLoading: false,
      error: null,
      upload: vi.fn(),
      remove: vi.fn(),
      analyze: vi.fn(),
    });
  });

  it("renders Documents heading", () => {
    render(<DocumentsPage />);
    expect(screen.getByText("Documents")).toBeInTheDocument();
  });

  it("renders DocumentUploader", () => {
    render(<DocumentsPage />);
    expect(screen.getByTestId("doc-uploader")).toBeInTheDocument();
  });

  it("shows loading skeletons when loading", () => {
    mockUseDocuments.mockReturnValue({
      documents: [],
      isLoading: true,
      error: null,
      upload: vi.fn(),
      remove: vi.fn(),
      analyze: vi.fn(),
    });
    render(<DocumentsPage />);
    const skeletons = screen.getAllByTestId("skeleton");
    expect(skeletons.length).toBe(3);
  });

  it("shows empty state message when no documents", () => {
    render(<DocumentsPage />);
    expect(screen.getByText("Your document vault is empty")).toBeInTheDocument();
    expect(screen.getByText("PDF")).toBeInTheDocument();
  });

  it("renders document viewers for each document", () => {
    mockUseDocuments.mockReturnValue({
      documents: [
        { id: "1", filename: "report.pdf" },
        { id: "2", filename: "data.csv" },
      ],
      isLoading: false,
      error: null,
      upload: vi.fn(),
      remove: vi.fn(),
      analyze: vi.fn(),
    });
    render(<DocumentsPage />);
    expect(screen.getByText("report.pdf")).toBeInTheDocument();
    expect(screen.getByText("data.csv")).toBeInTheDocument();
  });

  it("groups byte-identical uploads into one visible document", () => {
    mockUseDocuments.mockReturnValue({
      documents: [
        { id: "1", filename: "IMG_4007.jpg", contentSha256: "same", status: "pending" },
        { id: "2", filename: "IMG_4007.jpg", contentSha256: "same", status: "pending" },
        { id: "3", filename: "IMG_4007.jpg", contentSha256: "same", status: "completed" },
        { id: "4", filename: "IMG_4008.jpg", contentSha256: "different", status: "pending" },
      ],
      isLoading: false,
      error: null,
      upload: vi.fn(),
      remove: vi.fn(),
      analyze: vi.fn(),
    });

    render(<DocumentsPage />);

    expect(screen.getAllByTestId("doc-viewer")).toHaveLength(2);
    expect(screen.getByText("IMG_4007.jpg · 3 identical uploads")).toBeInTheDocument();
  });

  it("shows error message when error exists", () => {
    mockUseDocuments.mockReturnValue({
      documents: [],
      isLoading: false,
      error: "Upload failed",
      upload: vi.fn(),
      remove: vi.fn(),
      analyze: vi.fn(),
    });
    render(<DocumentsPage />);
    expect(screen.getByText("Upload failed")).toBeInTheDocument();
  });
});
