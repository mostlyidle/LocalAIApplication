"use client";

import { useState } from "react";
import Link from "next/link";
import { FileText, Trash2, Search, Loader2, Database } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Document } from "@/types/document";
import { ExtractionResults } from "./ExtractionResults";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import * as api from "@/lib/api";

interface AnalysisData {
  text: string;
  answer?: string | null;
  tables: { page?: number | null; headers: string[]; rows: string[][] }[];
  metadata: Record<string, unknown>;
  page_count?: number | null;
  word_count: number;
}

interface DocumentViewerProps {
  document: Document;
  duplicateCount?: number;
  duplicateStatusSummary?: string;
  onDelete: (id: string) => void;
  onAnalyze: (id: string, prompt?: string) => Promise<AnalysisData>;
}

export function DocumentViewer({ document: doc, duplicateCount = 1, duplicateStatusSummary, onDelete, onAnalyze }: DocumentViewerProps) {
  const [prompt, setPrompt] = useState("");
  const [analysis, setAnalysis] = useState<AnalysisData | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);
  const [indexDialogOpen, setIndexDialogOpen] = useState(false);
  const [containers, setContainers] = useState<api.RAGContainer[]>([]);
  const [containerName, setContainerName] = useState("");
  const [isIndexing, setIsIndexing] = useState(false);
  const [indexError, setIndexError] = useState<string | null>(null);

  const handleAnalyze = async () => {
    setIsAnalyzing(true);
    setAnalyzeError(null);
    try {
      const result = await onAnalyze(doc.id, prompt || undefined);
      setAnalysis(result);
    } catch {
      setAnalyzeError("Analysis failed. Please try again.");
    } finally {
      setIsAnalyzing(false);
    }
  };

  const openIndexDialog = async () => {
    setIndexError(null);
    setIndexDialogOpen(true);
    try {
      const result = await api.getRAGContainers();
      setContainers(result);
      setContainerName((current) => result.some((item) => item.name === current)
        ? current
        : result[0]?.name ?? "");
    } catch (error) {
      setIndexError(error instanceof Error ? error.message : "Could not load RAG indexes.");
    }
  };

  const handleIndex = async () => {
    setIsIndexing(true);
    setIndexError(null);
    try {
      if (!containerName) return;
      await api.queueDocumentInRAGContainer(containerName, doc.id);
      setIndexDialogOpen(false);
    } catch (error) {
      setIndexError(error instanceof Error ? error.message : "Could not add this document to the index.");
    } finally {
      setIsIndexing(false);
    }
  };

  const statusColor = {
    pending: "bg-peach-ink",
    processing: "bg-sky-ink",
    completed: "bg-mint-ink",
    failed: "bg-destructive",
  }[doc.status] ?? "bg-muted-foreground";

  const sizeLabel =
    doc.sizeBytes < 1024
      ? `${doc.sizeBytes} B`
      : doc.sizeBytes < 1024 * 1024
      ? `${(doc.sizeBytes / 1024).toFixed(1)} KB`
      : `${(doc.sizeBytes / (1024 * 1024)).toFixed(1)} MB`;

  return (
    <Card className="min-w-0 overflow-hidden">
      <CardHeader className="pb-3">
        <div className="flex min-w-0 items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-2">
            <FileText className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
            <CardTitle className="min-w-0 break-words text-sm [overflow-wrap:anywhere]">
              {doc.filename}
            </CardTitle>
          </div>
          <Button
            variant="ghost"
            size="icon"
            aria-label={duplicateCount > 1
              ? `Delete one of ${duplicateCount} identical uploads: ${doc.filename}`
              : `Delete ${doc.filename}`}
            className="h-9 w-9 shrink-0 text-muted-foreground hover:text-destructive"
            onClick={() => onDelete(doc.id)}
          >
            <Trash2 className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="min-w-0 space-y-3">
        <div className="flex flex-wrap gap-2 text-xs">
          <Badge variant="secondary">{doc.format}</Badge>
          <Badge variant="outline">{sizeLabel}</Badge>
          {duplicateCount > 1 ? (
            <Badge variant="outline">{duplicateCount} identical uploads</Badge>
          ) : (
            <div className="flex items-center gap-1">
              <div className={`h-1.5 w-1.5 rounded-full ${statusColor}`} />
              <span className="text-muted-foreground">{doc.status}</span>
            </div>
          )}
          {duplicateCount > 1 && duplicateStatusSummary && (
            <span className="text-muted-foreground">{duplicateStatusSummary}</span>
          )}
          {doc.pageCount && (
            <span className="text-muted-foreground">{doc.pageCount} pages</span>
          )}
          {doc.wordCount > 0 && (
            <span className="text-muted-foreground">{doc.wordCount.toLocaleString()} words</span>
          )}
        </div>

        {doc.errorMessage && (
          <p className="text-xs text-destructive">{doc.errorMessage}</p>
        )}

        <Separator />

        <div className="space-y-2">
          <Textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Ask about this document... (optional)"
            className="min-h-[60px] w-full min-w-0 resize-y text-sm"
            rows={2}
          />
          <Button
            size="sm"
            onClick={handleAnalyze}
            disabled={isAnalyzing || doc.status === "processing"}
            className="w-full"
          >
            {isAnalyzing ? (
              <Loader2 className="mr-2 h-3 w-3 animate-spin" />
            ) : (
              <Search className="mr-2 h-3 w-3" />
            )}
            Analyze
          </Button>
          <div className="grid grid-cols-1 gap-2">
            <Button asChild size="sm" variant="outline" className="min-h-10 w-full whitespace-normal px-3 text-center leading-snug">
              <Link href={`/chat?documentId=${encodeURIComponent(doc.id)}`}>
                <Search className="mr-2 size-3.5" aria-hidden="true" /> Ask in Chat
              </Link>
            </Button>
            <Button type="button" size="sm" variant="outline" className="min-h-10 w-full whitespace-normal px-3 text-center leading-snug" onClick={() => void openIndexDialog()}>
              <Database className="mr-2 size-3.5" aria-hidden="true" /> Add to Knowledge Base
            </Button>
          </div>
        </div>

        {analyzeError && (
          <p className="text-xs text-destructive">{analyzeError}</p>
        )}

        {analysis && (
          <ExtractionResults
            text={analysis.text}
            answer={analysis.answer}
            tables={analysis.tables}
            metadata={analysis.metadata}
            pageCount={analysis.page_count}
            wordCount={analysis.word_count}
          />
        )}
      </CardContent>
      <Dialog open={indexDialogOpen} onOpenChange={setIndexDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add to Knowledge Base</DialogTitle>
              <DialogDescription>
                Choose the private container that should index <span className="break-all">{doc.filename}</span>.
              </DialogDescription>
          </DialogHeader>
          {containers.length > 0 ? (
            <label className="grid gap-2 text-sm font-medium" htmlFor={`rag-container-${doc.id}`}>
              Target container
              <Select value={containerName} onValueChange={setContainerName}>
                <SelectTrigger id={`rag-container-${doc.id}`} className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent position="popper" align="start">
                  {containers.map((container) => <SelectItem key={container.name} value={container.name}>{container.display_name}</SelectItem>)}
                </SelectContent>
              </Select>
            </label>
          ) : !indexError ? (
            <p className="text-sm text-muted-foreground">Create a private container before adding documents.</p>
          ) : null}
          {indexError && <p role="alert" className="text-sm text-destructive">{indexError}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setIndexDialogOpen(false)}>Cancel</Button>
            {containers.length === 0 && !indexError ? (
              <Button asChild><Link href="/rag">Create a container</Link></Button>
            ) : (
              <Button type="button" onClick={() => void handleIndex()} disabled={isIndexing || !containerName}>
              {isIndexing && <Loader2 className="mr-2 size-4 animate-spin" aria-hidden="true" />}
                Add to container
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
