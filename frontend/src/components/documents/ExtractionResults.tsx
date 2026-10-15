"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { FileText, TableIcon, Info } from "lucide-react";
import { MarkdownContent } from "@/components/chat/MarkdownContent";

interface ExtractedTable {
  page?: number | null;
  headers: string[];
  rows: string[][];
}

interface ExtractionResultsProps {
  text: string;
  answer?: string | null;
  tables: ExtractedTable[];
  metadata: Record<string, unknown>;
  pageCount?: number | null;
  wordCount: number;
}

export function ExtractionResults({
  text,
  answer,
  tables,
  metadata,
  pageCount,
  wordCount,
}: ExtractionResultsProps) {
  return (
    <div className="space-y-4">
      {answer && (
        <Card className="min-w-0 overflow-hidden">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Answer</CardTitle>
          </CardHeader>
          <CardContent className="min-w-0">
            <div className="max-h-96 min-w-0 overflow-x-hidden overflow-y-auto">
              <MarkdownContent content={answer} className="text-sm leading-relaxed" />
            </div>
          </CardContent>
        </Card>
      )}
      {/* Summary badges */}
      <div className="flex flex-wrap gap-2">
        {pageCount != null && (
          <Badge variant="secondary">{pageCount} pages</Badge>
        )}
        {wordCount > 0 && (
          <Badge variant="secondary">
            {wordCount.toLocaleString()} words
          </Badge>
        )}
        {tables.length > 0 && (
          <Badge variant="secondary">
            {tables.length} table{tables.length !== 1 ? "s" : ""}
          </Badge>
        )}
        {Object.keys(metadata).length > 0 && (
          <Badge variant="outline">
            {Object.keys(metadata).length} metadata fields
          </Badge>
        )}
      </div>

      {/* Extracted text */}
      {text && (
        <Card className="min-w-0 overflow-hidden">
          <details>
            <summary className="flex min-h-16 cursor-pointer list-none flex-wrap items-center justify-between gap-2 px-6 py-4">
              <span className="flex items-center gap-2 text-sm font-semibold">
                <FileText className="h-4 w-4 shrink-0" aria-hidden="true" />
                Extracted text preview
              </span>
              <span className="text-xs text-muted-foreground">
                Expand to view the first 5,000 characters
              </span>
            </summary>
            <CardContent className="min-w-0 pt-0">
              <div className="max-h-64 overflow-x-hidden overflow-y-auto rounded-lg border bg-muted/40 p-3">
                <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed text-muted-foreground [overflow-wrap:anywhere]">
                  {text.length > 5000 ? `${text.slice(0, 5000)}...` : text}
                </pre>
              </div>
            </CardContent>
          </details>
        </Card>
      )}

      {/* Extracted tables */}
      {tables.map((table, idx) => (
        <Card key={idx} className="min-w-0 overflow-hidden">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <TableIcon className="h-4 w-4" />
              Table {idx + 1}
              {table.page != null && (
                <span className="text-xs font-normal text-muted-foreground">
                  (page {table.page})
                </span>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="min-w-0 p-0">
            <div className="max-h-64 overflow-auto">
              <Table>
                {table.headers.length > 0 && (
                  <TableHeader>
                    <TableRow>
                      {table.headers.map((h, i) => (
                        <TableHead key={i} className="text-xs">
                          {h}
                        </TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                )}
                <TableBody>
                  {table.rows.slice(0, 50).map((row, ri) => (
                    <TableRow key={ri}>
                      {row.map((cell, ci) => (
                        <TableCell key={ci} className="text-xs">
                          {cell}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {table.rows.length > 50 && (
                <p className="p-2 text-center text-xs text-muted-foreground">
                  Showing 50 of {table.rows.length} rows
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      ))}

      {/* Metadata */}
      {Object.keys(metadata).length > 0 && (
        <Card className="min-w-0 overflow-hidden">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Info className="h-4 w-4" />
              Metadata
            </CardTitle>
          </CardHeader>
          <CardContent className="min-w-0">
            <div className="grid min-w-0 grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-1">
              {Object.entries(metadata).map(([key, value]) => (
                <div key={key} className="contents">
                  <span className="break-words text-xs font-medium [overflow-wrap:anywhere]">{key}</span>
                  <span className="min-w-0 break-words text-xs text-muted-foreground [overflow-wrap:anywhere]">
                    {typeof value === "object"
                      ? JSON.stringify(value)
                      : String(value)}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
