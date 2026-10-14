"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Database, Loader2, RotateCcw, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  createRAGContainer,
  deleteRAGContainer,
  deleteRAGContainerFile,
  getRAGContainerFiles,
  loadRAGContainer,
  retryRAGContainerFile,
  type RAGContainer,
  type RAGContainerFile,
} from "@/lib/api";
import { ContainerUploader } from "./ContainerUploader";

interface ContainerManagerProps {
  containers: RAGContainer[];
  selectedName: string;
  onSelect: (name: string) => void;
  onRefresh: () => Promise<void>;
}

export function ContainerManager({ containers, selectedName, onSelect, onRefresh }: ContainerManagerProps) {
  const [displayName, setDisplayName] = useState("");
  const [files, setFiles] = useState<RAGContainerFile[]>([]);
  const [isLoadingFiles, setIsLoadingFiles] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const filesRequestId = useRef(0);
  const selectedNameRef = useRef(selectedName);
  selectedNameRef.current = selectedName;
  const active = containers.find((container) => container.name === selectedName);
  const isWorking = Boolean(active && active.queued_file_count + active.processing_file_count > 0);

  const refreshFiles = useCallback(async (expectedName = selectedName) => {
    if (expectedName !== selectedNameRef.current) return;
    const requestId = ++filesRequestId.current;
    if (!expectedName) {
      setFiles([]);
      setIsLoadingFiles(false);
      return;
    }
    setIsLoadingFiles(true);
    try {
      const nextFiles = await getRAGContainerFiles(expectedName);
      if (requestId === filesRequestId.current && selectedNameRef.current === expectedName) {
        setFiles(nextFiles);
        setError("");
      }
    } catch (loadError) {
      if (requestId === filesRequestId.current && selectedNameRef.current === expectedName) {
        setError(loadError instanceof Error ? loadError.message : "Could not load container files.");
      }
    } finally {
      if (requestId === filesRequestId.current && selectedNameRef.current === expectedName) {
        setIsLoadingFiles(false);
      }
    }
  }, [selectedName]);

  useEffect(() => {
    void refreshFiles();
    return () => { filesRequestId.current += 1; };
  }, [refreshFiles]);

  useEffect(() => {
    if (!isWorking) return;
    const timer = window.setInterval(() => {
      void Promise.all([refreshFiles(), onRefresh()]);
    }, 2_000);
    return () => window.clearInterval(timer);
  }, [isWorking, onRefresh, refreshFiles]);

  const failures = useMemo(() => files.filter((file) => file.status === "failed").length, [files]);

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault();
    if (!displayName.trim() || isCreating) return;
    setError("");
    setNotice("");
    setIsCreating(true);
    try {
      const container = await createRAGContainer(displayName.trim());
      setDisplayName("");
      onSelect(container.name);
      await onRefresh();
      setNotice(`Created “${container.display_name}”. Add files, then load index.`);
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "Could not create container.");
    } finally {
      setIsCreating(false);
    }
  };

  const handleLoad = async () => {
    if (!active || isLoading) return;
    const operationName = active.name;
    setError("");
    setNotice("");
    setIsLoading(true);
    try {
      const result = await loadRAGContainer(active.name);
      if (selectedNameRef.current !== operationName) return;
      await Promise.all([refreshFiles(), onRefresh()]);
      setNotice(result.queued ? `Queued ${result.queued} file${result.queued === 1 ? "" : "s"} for indexing.` : "No staged files to load.");
    } catch (loadError) {
      if (selectedNameRef.current === operationName) {
        setError(loadError instanceof Error ? loadError.message : "Could not start indexing.");
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleRetry = async (file: RAGContainerFile) => {
    if (!active) return;
    const operationName = active.name;
    setError("");
    try {
      await retryRAGContainerFile(active.name, file.id);
      if (selectedNameRef.current !== operationName) return;
      await Promise.all([refreshFiles(), onRefresh()]);
    } catch (retryError) {
      if (selectedNameRef.current === operationName) {
        setError(retryError instanceof Error ? retryError.message : "Could not retry file.");
      }
    }
  };

  const handleRemoveFile = async (file: RAGContainerFile) => {
    if (!active) return;
    const operationName = active.name;
    setError("");
    try {
      await deleteRAGContainerFile(active.name, file.id);
      if (selectedNameRef.current !== operationName) return;
      await Promise.all([refreshFiles(), onRefresh()]);
    } catch (removeError) {
      if (selectedNameRef.current === operationName) {
        setError(removeError instanceof Error ? removeError.message : "Could not remove file.");
      }
    }
  };

  const handleDeleteContainer = async () => {
    if (!active || isWorking) return;
    if (!window.confirm(`Delete “${active.display_name}” and its indexed data? Uploaded source files stay in Documents.`)) return;
    setError("");
    try {
      await deleteRAGContainer(active.name);
      onSelect("");
      setFiles([]);
      await onRefresh();
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Could not delete container.");
    }
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <Database aria-hidden="true" className="size-4 text-muted-foreground" />
          <CardTitle className="text-sm">Vector index containers</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">{error}</p>}
        {notice && <p role="status" aria-live="polite" className="rounded-lg bg-muted p-3 text-sm">{notice}</p>}

        <form onSubmit={(event) => { void handleCreate(event); }} className="flex flex-col gap-2 sm:flex-row">
          <label htmlFor="rag-container-name" className="sr-only">New container name</label>
          <Input
            id="rag-container-name"
            value={displayName}
            maxLength={120}
            onChange={(event) => setDisplayName(event.target.value)}
            placeholder="e.g. Project research"
            className="min-w-0 flex-1"
          />
          <Button type="submit" disabled={!displayName.trim() || isCreating}>
            {isCreating && <Loader2 aria-hidden="true" className="mr-2 size-4 animate-spin" />}
            Create container
          </Button>
        </form>

        {containers.length > 0 && (
          <div>
            <label htmlFor="rag-container-select" className="mb-1 block text-sm font-medium">Container</label>
            <Select value={active?.name ?? ""} onValueChange={onSelect}>
              <SelectTrigger id="rag-container-select" className="w-full"><SelectValue placeholder="Select a container" /></SelectTrigger>
              <SelectContent position="popper" align="start">
                {containers.map((container) => (
                  <SelectItem key={container.name} value={container.name}>
                    {container.display_name} ({container.file_count} files)
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {!active ? (
          <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
            Create a container to stage files in a private vector index.
          </p>
        ) : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Badge variant="secondary">{active.file_count} files</Badge>
              <Badge variant="secondary">{active.chunk_count} chunks</Badge>
              {active.failed_file_count > 0 && <Badge variant="destructive">{active.failed_file_count} failed</Badge>}
              <span className="text-muted-foreground">{active.indexed_file_count} indexed</span>
            </div>

            {isWorking && (
              <div aria-live="polite" className="space-y-1 text-sm">
                <p>{active.indexed_file_count + active.failed_file_count} of {active.file_count} files processed</p>
                <progress
                  aria-label="Container indexing progress"
                  max={Math.max(active.file_count, 1)}
                  value={active.indexed_file_count + active.failed_file_count}
                  className="h-2 w-full accent-primary"
                />
                <p className="text-xs text-muted-foreground">
                  {active.processing_file_count} processing · {active.queued_file_count} queued
                </p>
              </div>
            )}

            <ContainerUploader containerName={active.name} onUploaded={async () => {
              const operationName = active.name;
              if (selectedNameRef.current !== operationName) return;
              await refreshFiles(operationName);
              if (selectedNameRef.current !== operationName) return;
              await onRefresh();
              setNotice("Files staged. Load index when ready.");
            }} />

            <div className="flex flex-wrap items-center gap-2">
              <Button type="button" onClick={() => { void handleLoad(); }} disabled={active.staged_file_count === 0 || isLoading}>
                {isLoading && <Loader2 aria-hidden="true" className="mr-2 size-4 animate-spin" />}
                Load {active.staged_file_count} staged {active.staged_file_count === 1 ? "file" : "files"}
              </Button>
              <Button type="button" variant="outline" onClick={() => { void handleDeleteContainer(); }} disabled={isWorking}>
                <Trash2 aria-hidden="true" className="mr-2 size-4" /> Delete container
              </Button>
            </div>

            <div className="space-y-2" aria-label={`${active.display_name} files`}>
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold">Files</h3>
                {failures > 0 && <span className="text-xs text-destructive">{failures} need retry</span>}
              </div>
              {isLoadingFiles ? (
                <p role="status" className="text-sm text-muted-foreground">Loading files…</p>
              ) : files.length === 0 ? (
                <p className="text-sm text-muted-foreground">No files staged yet.</p>
              ) : (
                <ul className="max-h-64 space-y-2 overflow-y-auto">
                  {files.map((file) => (
                    <li key={file.id} className="flex min-w-0 items-start gap-2 rounded-lg border p-3">
                      <div className="min-w-0 flex-1">
                        <p className="break-all text-sm font-medium">{file.relative_path}</p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {statusLabel(file.status)} · {formatSize(file.size_bytes)}
                          {file.chunk_count > 0 && ` · ${file.chunk_count} chunks`}
                        </p>
                        {file.last_error && <p className="mt-1 text-xs text-destructive">{file.last_error}</p>}
                      </div>
                      {file.status === "failed" && (
                        <Button type="button" variant="outline" size="icon" aria-label={`Retry ${file.relative_path}`} onClick={() => { void handleRetry(file); }}>
                          <RotateCcw aria-hidden="true" className="size-4" />
                        </Button>
                      )}
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label={`Remove ${file.relative_path} from container`}
                        disabled={file.status === "processing" || file.status === "deleting"}
                        onClick={() => { void handleRemoveFile(file); }}
                      >
                        <Trash2 aria-hidden="true" className="size-4" />
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
              <p className="text-xs text-muted-foreground">Removing a file from container keeps its uploaded source in Documents.</p>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function statusLabel(status: string): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function formatSize(sizeBytes: number): string {
  if (sizeBytes < 1_000_000) return `${Math.max(sizeBytes / 1_000, 1).toFixed(1)} KB`;
  return `${(sizeBytes / 1_000_000).toFixed(1)} MB`;
}
