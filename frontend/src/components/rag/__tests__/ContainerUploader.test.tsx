import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ContainerUploader } from "../ContainerUploader";
import { uploadRAGContainerFiles } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  uploadRAGContainerFiles: vi.fn(),
}));

describe("ContainerUploader folder drop", () => {
  beforeEach(() => {
    vi.mocked(uploadRAGContainerFiles).mockResolvedValue({ files: [], failures: [] });
  });

  it("recursively stages a dropped folder and preserves relative paths", async () => {
    const rootFile = new File(["root"], "root-note.txt", { type: "text/plain" });
    const nestedFile = new File(["nested"], "nested-note.txt", { type: "text/plain" });

    const fileEntry = (name: string, fullPath: string, file: File): FileSystemFileEntry => ({
      isFile: true,
      isDirectory: false,
      name,
      fullPath,
      file: (callback) => callback(file),
    }) as FileSystemFileEntry;
    const rootEntry = fileEntry("root-note.txt", "/knowledge-base/root-note.txt", rootFile);
    const nestedEntry = fileEntry(
      "nested-note.txt",
      "/knowledge-base/reference/nested-note.txt",
      nestedFile,
    );
    const nestedDirectoryEntry = {
      isFile: false,
      isDirectory: true,
      name: "reference",
      fullPath: "/knowledge-base/reference",
      createReader: () => {
        let read = false;
        return {
          readEntries: (callback: (entries: FileSystemEntry[]) => void) => {
            callback(read ? [] : [nestedEntry]);
            read = true;
          },
        };
      },
    } as FileSystemDirectoryEntry;
    const directoryEntry = {
      isFile: false,
      isDirectory: true,
      name: "knowledge-base",
      fullPath: "/knowledge-base",
      createReader: () => {
        let read = false;
        return {
          readEntries: (callback: (entries: FileSystemEntry[]) => void) => {
            callback(read ? [] : [rootEntry, nestedDirectoryEntry]);
            read = true;
          },
        };
      },
    } as FileSystemDirectoryEntry;
    const item = { webkitGetAsEntry: () => directoryEntry } as unknown as DataTransferItem;

    render(<ContainerUploader containerName="drop-test" onUploaded={vi.fn().mockResolvedValue(undefined)} />);
    fireEvent.drop(screen.getByText("Drop files or folders here").closest(".border-dashed")!, {
      dataTransfer: { items: [item] },
    });

    await waitFor(() => {
      expect(uploadRAGContainerFiles).toHaveBeenCalledWith("drop-test", [
        { file: rootFile, relativePath: "knowledge-base/root-note.txt" },
        { file: nestedFile, relativePath: "knowledge-base/reference/nested-note.txt" },
      ]);
    });
  });
});
