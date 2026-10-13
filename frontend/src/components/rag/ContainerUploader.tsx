"use client";

import { useRef, useState } from "react";
import { FolderOpen, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ACCEPTED_FILE_TYPES } from "@/lib/constants";
import { uploadRAGContainerFiles } from "@/lib/api";

interface UploadEntry {
  file: File;
  relativePath: string;
}

interface ContainerUploaderProps {
  containerName: string;
  onUploaded: () => Promise<void>;
}

const MAX_BATCH_FILES = 100;
const MAX_BATCH_BYTES = 400 * 1024 * 1024;

export function ContainerUploader({ containerName, onUploaded }: ContainerUploaderProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [progress, setProgress] = useState("");
  const [errors, setErrors] = useState<string[]>([]);

  const upload = async (entries: UploadEntry[]) => {
    if (entries.length === 0 || isUploading) return;
    setIsUploading(true);
    setErrors([]);
    const failures: string[] = [];
    const batches: UploadEntry[][] = [];
    let batch: UploadEntry[] = [];
    let batchBytes = 0;
    for (const entry of entries) {
      if (batch.length && (batch.length >= MAX_BATCH_FILES || batchBytes + entry.file.size > MAX_BATCH_BYTES)) {
        batches.push(batch);
        batch = [];
        batchBytes = 0;
      }
      batch.push(entry);
      batchBytes += entry.file.size;
    }
    if (batch.length) batches.push(batch);

    let completed = 0;
    try {
      for (let index = 0; index < batches.length; index += 1) {
        const current = batches[index];
        setProgress(`Uploading batch ${index + 1} of ${batches.length} (${completed} of ${entries.length} files)`);
        try {
          const result = await uploadRAGContainerFiles(containerName, current);
          failures.push(...result.failures.map((failure) => `${failure.relative_path}: ${failure.message}`));
        } catch (error) {
          const message = error instanceof Error ? error.message : "Upload failed. Try again.";
          failures.push(...current.map(({ relativePath }) => `${relativePath}: ${message}`));
        }
        completed += current.length;
        await onUploaded();
      }
    } finally {
      setProgress("");
      setErrors(failures);
      setIsUploading(false);
    }
  };

  const handleDrop = async (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragOver(false);
    const items = Array.from(event.dataTransfer.items);
    const entries = (await Promise.all(items.map(readDroppedItem))).flat();
    if (entries.length) {
      await upload(entries);
    } else {
      setErrors(["Could not read dropped folder. Choose folder to select it."]);
    }
  };

  const handleInput = (event: React.ChangeEvent<HTMLInputElement>) => {
    const entries = Array.from(event.target.files ?? []).map((file) => ({
      file,
      relativePath: file.webkitRelativePath || file.name,
    }));
    event.target.value = "";
    void upload(entries);
  };

  return (
    <div
      className={`rounded-xl border-2 border-dashed p-4 transition-colors ${isDragOver ? "border-primary bg-primary/5" : "border-border"}`}
      onDragOver={(event) => { event.preventDefault(); setIsDragOver(true); }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={(event) => { void handleDrop(event); }}
    >
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={ACCEPTED_FILE_TYPES.join(",")}
        aria-label="Select files to add to container"
        className="sr-only"
        onChange={handleInput}
      />
      <input
        ref={folderInputRef}
        type="file"
        multiple
        accept={ACCEPTED_FILE_TYPES.join(",")}
        aria-label="Select folder to add to container"
        className="sr-only"
        onChange={handleInput}
        {...{ webkitdirectory: "" }}
      />
      <div className="flex flex-col items-center gap-3 text-center">
        <Upload aria-hidden="true" className="size-7 text-muted-foreground" />
        <div>
          <p className="text-sm font-medium">Drop files or folders here</p>
          <p className="mt-1 text-xs text-muted-foreground">PDF, Office, text, CSV, HTML, and images. Max 50 MB per file.</p>
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          <Button type="button" variant="outline" disabled={isUploading} onClick={() => fileInputRef.current?.click()}>
            <Upload aria-hidden="true" className="mr-2 size-4" /> Select files
          </Button>
          <Button type="button" variant="outline" disabled={isUploading} onClick={() => folderInputRef.current?.click()}>
            <FolderOpen aria-hidden="true" className="mr-2 size-4" /> Select folder
          </Button>
        </div>
        {isUploading && <p role="status" aria-live="polite" className="text-sm">{progress}</p>}
      </div>
      {errors.length > 0 && (
        <div role="alert" className="mt-4 rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
          <p className="font-medium">Some files could not be added.</p>
          <ul className="mt-1 list-inside list-disc">
            {errors.map((error, index) => <li key={`${index}-${error}`}>{error}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

async function readDroppedItem(item: DataTransferItem): Promise<UploadEntry[]> {
  const entry = item.webkitGetAsEntry();
  if (entry) return readEntry(entry);
  const file = item.getAsFile();
  return file ? [{ file, relativePath: file.name }] : [];
}

async function readEntry(entry: FileSystemEntry): Promise<UploadEntry[]> {
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) => {
      (entry as FileSystemFileEntry).file(resolve, reject);
    });
    return [{ file, relativePath: entry.fullPath.replace(/^\/+/, "") || file.name }];
  }

  if (!entry.isDirectory) return [];
  const reader = (entry as FileSystemDirectoryEntry).createReader();
  const children: FileSystemEntry[] = [];
  while (true) {
    const batch = await new Promise<FileSystemEntry[]>((resolve, reject) => reader.readEntries(resolve, reject));
    if (batch.length === 0) break;
    children.push(...batch);
  }
  const nested = await Promise.all(children.map(readEntry));
  return nested.flat();
}
