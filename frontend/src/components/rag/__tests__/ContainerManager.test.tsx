import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ContainerManager } from "../ContainerManager";

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  deleteContainer: vi.fn(),
  deleteFile: vi.fn(),
  getFiles: vi.fn(),
  load: vi.fn(),
  retry: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  createRAGContainer: mocks.create,
  deleteRAGContainer: mocks.deleteContainer,
  deleteRAGContainerFile: mocks.deleteFile,
  getRAGContainerFiles: mocks.getFiles,
  loadRAGContainer: mocks.load,
  retryRAGContainerFile: mocks.retry,
}));

vi.mock("../ContainerUploader", () => ({
  ContainerUploader: () => <div>Container uploader</div>,
}));

const container = {
  name: "container_research",
  display_name: "Research",
  file_count: 1,
  indexed_file_count: 0,
  staged_file_count: 1,
  queued_file_count: 0,
  processing_file_count: 0,
  failed_file_count: 0,
  chunk_count: 0,
};

const file = {
  id: "file-notes",
  relative_path: "project/notes.txt",
  status: "failed",
  chunk_count: 0,
  size_bytes: 12,
  last_error: "Could not parse file.",
};

describe("ContainerManager", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getFiles.mockResolvedValue([]);
    mocks.create.mockResolvedValue(container);
    mocks.load.mockResolvedValue({ queued: 1 });
    mocks.retry.mockResolvedValue(file);
    mocks.deleteFile.mockResolvedValue({ deleted: true });
  });

  it("creates a named container and selects it", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    render(
      <ContainerManager
        containers={[]}
        selectedName=""
        onSelect={onSelect}
        onRefresh={onRefresh}
      />,
    );

    await user.type(screen.getByLabelText("New container name"), "Research");
    await user.click(screen.getByRole("button", { name: "Create container" }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith("Research"));
    expect(onSelect).toHaveBeenCalledWith(container.name);
    expect(onRefresh).toHaveBeenCalled();
  });

  it("loads staged files into the selected index", async () => {
    const user = userEvent.setup();
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    render(
      <ContainerManager
        containers={[container]}
        selectedName={container.name}
        onSelect={vi.fn()}
        onRefresh={onRefresh}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Load 1 staged file" }));

    await waitFor(() => expect(mocks.load).toHaveBeenCalledWith(container.name));
  });

  it("retries and removes individual files", async () => {
    const user = userEvent.setup();
    mocks.getFiles.mockResolvedValue([file]);
    render(
      <ContainerManager
        containers={[{ ...container, staged_file_count: 0, failed_file_count: 1 }]}
        selectedName={container.name}
        onSelect={vi.fn()}
        onRefresh={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Retry project/notes.txt" }));
    await waitFor(() => expect(mocks.retry).toHaveBeenCalledWith(container.name, file.id));

    await user.click(screen.getByRole("button", { name: "Remove project/notes.txt from container" }));
    await waitFor(() => expect(mocks.deleteFile).toHaveBeenCalledWith(container.name, file.id));
  });
});
