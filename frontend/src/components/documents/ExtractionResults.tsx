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
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { FileText, TableIcon, Info } from "lucide-react";

interface ExtractedTable {
  page?: number | null;
  headers: string[];
  rows: string[][];
}

interface ExtractionResultsProps {
  text: string;
  tables: ExtractedTable[];
  metadata: Record<string, unknown>;
  pageCount?: number | null;
  wordCount: number;
}

export function ExtractionResults({
  text,
  tables,
  metadata,
  pageCount,
  wordCount,
}: ExtractionResultsProps) {
  return (
    <div className="space-y-4">
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
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <FileText className="h-4 w-4" />
              Extracted Text
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ScrollArea className="max-h-64">
              <pre className="whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">
                {text.length > 5000 ? `${text.slice(0, 5000)}...` : text}
              </pre>
            </ScrollArea>
          </CardContent>
        </Card>
      )}

      {/* Extracted tables */}
      {tables.map((table, idx) => (
        <Card key={idx}>
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
          <CardContent className="p-0">
            <ScrollArea className="max-h-64">
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
            </ScrollArea>
          </CardContent>
        </Card>
      ))}

      {/* Metadata */}
      {Object.keys(metadata).length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Info className="h-4 w-4" />
              Metadata
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1">
              {Object.entries(metadata).map(([key, value]) => (
                <div key={key} className="contents">
                  <span className="truncate text-xs font-medium">{key}</span>
                  <span className="truncate text-xs text-muted-foreground">
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
