"use client";

import { useCallback, useRef, useState } from "react";
import { Upload, LoaderCircle, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { ACCEPTED_FILE_TYPES, MAX_FILE_SIZE } from "@/lib/constants";

interface DocumentUploaderProps {
  onUpload: (file: File) => Promise<unknown>;
}

export function DocumentUploader({ onUpload }: DocumentUploaderProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const validateFile = (file: File): string | null => {
    if (file.size > MAX_FILE_SIZE) {
      return `File too large. Maximum size is ${MAX_FILE_SIZE / 1024 / 1024}MB.`;
    }
    const ext = "." + file.name.split(".").pop()?.toLowerCase();
    if (!ACCEPTED_FILE_TYPES.includes(ext)) {
      return `Unsupported file type: ${ext}`;
    }
    return null;
  };

  const handleFile = useCallback(async (file: File) => {
    const validationError = validateFile(file);
    if (validationError) {
      setError(validationError);
      return;
    }
    setError(null);
    setIsUploading(true);
    try {
      await onUpload(file);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setIsUploading(false);
    }
  }, [onUpload]);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
      if (inputRef.current) inputRef.current.value = "";
    },
    [handleFile]
  );

  return (
    <Card
      className={cn(
        "border-2 border-dashed transition-colors",
        isDragOver && "border-primary bg-primary/5",
        error && "border-destructive"
      )}
      onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={handleDrop}
    >
      <CardContent className="flex flex-col items-center gap-3 py-8">
        {isUploading ? (
          <LoaderCircle className="h-10 w-10 animate-spin text-primary" />
        ) : (
          <Upload className="h-10 w-10 text-muted-foreground" />
        )}
        <div className="text-center">
          <p className="text-sm font-medium">
            {isUploading ? "Uploading..." : "Drop a file here or click to browse"}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            PDF, DOCX, XLSX, CSV, images, and more (max 50MB)
          </p>
        </div>
        {error && (
          <div className="flex items-center gap-2 text-xs text-destructive">
            <X className="h-3 w-3" />
            {error}
          </div>
        )}
        <Button
          variant="outline"
          size="sm"
          onClick={() => inputRef.current?.click()}
          disabled={isUploading}
        >
          Select File
        </Button>
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          accept={ACCEPTED_FILE_TYPES.join(",")}
          onChange={handleChange}
        />
      </CardContent>
    </Card>
  );
}
