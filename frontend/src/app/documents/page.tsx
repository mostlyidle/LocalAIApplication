"use client";

import { FileText } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { useDocuments } from "@/hooks/useDocuments";
import { DocumentUploader } from "@/components/documents/DocumentUploader";
import { DocumentViewer } from "@/components/documents/DocumentViewer";

export default function DocumentsPage() {
  const { documents, isLoading, error, upload, remove, analyze } = useDocuments();

  return (
    <div className="container mx-auto max-w-5xl p-6">
      <div className="mb-6 flex items-center gap-2">
        <FileText className="h-6 w-6 text-amber-500" />
        <h1 className="text-xl font-bold">Documents</h1>
      </div>

      <div className="mb-6">
        <DocumentUploader onUpload={upload} />
      </div>

      {error && (
        <div className="mb-4 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-64 rounded-lg" />
          ))}
        </div>
      ) : documents.length === 0 ? (
        <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">
          No documents uploaded yet
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {documents.map((doc) => (
            <DocumentViewer
              key={doc.id}
              document={doc}
              onDelete={remove}
              onAnalyze={analyze}
            />
          ))}
        </div>
      )}
    </div>
  );
}
