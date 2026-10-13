"use client";

import { FileText } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { useDocuments } from "@/hooks/useDocuments";
import { DocumentUploader } from "@/components/documents/DocumentUploader";
import { DocumentViewer } from "@/components/documents/DocumentViewer";

export default function DocumentsPage() {
  const { documents, isLoading, error, upload, remove, analyze } = useDocuments();

  return (
    <div className="container mx-auto max-w-5xl px-4 py-6 sm:p-8">
      <div className="mb-6 flex items-center gap-3">
        <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-peach-soft text-peach-ink"><FileText className="h-6 w-6" aria-hidden="true" /></span>
        <div><h1 className="text-2xl font-bold">Documents</h1><p className="mt-1 text-sm text-muted-foreground">A fresh perspective on your files.</p></div>
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
