"use client";

/* Hallmark · genre: playful · macrostructure: Catalogue · design-system: design.md · designed-as-app */

import { useMemo } from "react";
import { FileText, FileUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useDocuments } from "@/hooks/useDocuments";
import { DocumentUploader } from "@/components/documents/DocumentUploader";
import { DocumentViewer } from "@/components/documents/DocumentViewer";

export default function DocumentsPage() {
  const { documents, isLoading, error, upload, remove, analyze } = useDocuments();
  const documentGroups = useMemo(() => {
    const groups = new Map<string, typeof documents>();
    for (const document of documents) {
      const key = document.contentSha256 ?? document.id;
      groups.set(key, [...(groups.get(key) ?? []), document]);
    }
    return Array.from(groups.values()).flatMap((copies) => {
      const [document] = copies;
      if (!document) return [];
      const statusCounts = (["completed", "processing", "pending", "failed"] as const)
        .map((status) => {
          const count = copies.filter((copy) => copy.status === status).length;
          return count > 0 ? `${count} ${status}` : null;
        })
        .filter((status): status is string => status !== null);
      return [{ document, duplicateCount: copies.length, statusSummary: statusCounts.join(" · ") }];
    });
  }, [documents]);

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
        <div className="flex min-h-56 flex-col items-center justify-center rounded-2xl border border-dashed bg-card/60 px-6 py-8 text-center">
          <span className="mb-4 grid size-16 place-items-center rounded-2xl bg-peach-soft text-peach-ink">
            <FileUp className="size-10" aria-hidden="true" />
          </span>
          <h2 className="text-lg font-semibold">Your document vault is empty</h2>
          <p className="mt-2 max-w-lg text-sm text-muted-foreground">
            Upload PDFs, Office documents, CSVs, or images to summarize, chat, or index them.
          </p>
          <div className="mt-4 flex flex-wrap justify-center gap-2">
            {["PDF", "DOCX", "XLSX", "CSV", "PNG", "TXT"].map((format) => (
              <Badge key={format} variant="secondary">{format}</Badge>
            ))}
          </div>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {documentGroups.map(({ document, duplicateCount, statusSummary }) => (
            <DocumentViewer
              key={document.contentSha256 ?? document.id}
              document={document}
              duplicateCount={duplicateCount}
              duplicateStatusSummary={statusSummary}
              onDelete={remove}
              onAnalyze={analyze}
            />
          ))}
        </div>
      )}
    </div>
  );
}
