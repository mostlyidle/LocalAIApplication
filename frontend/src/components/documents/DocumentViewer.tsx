"use client";

import { useState } from "react";
import { FileText, Trash2, Search, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import type { Document } from "@/types/document";
import { ExtractionResults } from "./ExtractionResults";

interface AnalysisData {
  text: string;
  tables: { page?: number | null; headers: string[]; rows: string[][] }[];
  metadata: Record<string, unknown>;
  page_count?: number | null;
  word_count: number;
}

interface DocumentViewerProps {
  document: Document;
  onDelete: (id: string) => void;
  onAnalyze: (id: string, prompt?: string) => Promise<AnalysisData>;
}

export function DocumentViewer({ document: doc, onDelete, onAnalyze }: DocumentViewerProps) {
  const [prompt, setPrompt] = useState("");
  const [analysis, setAnalysis] = useState<AnalysisData | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);

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

  const statusColor = {
    pending: "bg-yellow-500",
    processing: "bg-blue-500",
    completed: "bg-green-500",
    failed: "bg-red-500",
  }[doc.status] ?? "bg-gray-500";

  const sizeLabel =
    doc.sizeBytes < 1024
      ? `${doc.sizeBytes} B`
      : doc.sizeBytes < 1024 * 1024
      ? `${(doc.sizeBytes / 1024).toFixed(1)} KB`
      : `${(doc.sizeBytes / (1024 * 1024)).toFixed(1)} MB`;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-sm">{doc.filename}</CardTitle>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-muted-foreground hover:text-destructive"
            onClick={() => onDelete(doc.id)}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-2 text-xs">
          <Badge variant="secondary">{doc.format}</Badge>
          <Badge variant="outline">{sizeLabel}</Badge>
          <div className="flex items-center gap-1">
            <div className={`h-1.5 w-1.5 rounded-full ${statusColor}`} />
            <span className="text-muted-foreground">{doc.status}</span>
          </div>
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
            className="min-h-[60px] resize-none text-xs"
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
        </div>

        {analyzeError && (
          <p className="text-xs text-destructive">{analyzeError}</p>
        )}

        {analysis && (
          <ExtractionResults
            text={analysis.text}
            tables={analysis.tables}
            metadata={analysis.metadata}
            pageCount={analysis.page_count}
            wordCount={analysis.word_count}
          />
        )}
      </CardContent>
    </Card>
  );
}
