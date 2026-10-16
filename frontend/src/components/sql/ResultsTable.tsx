"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ResultsTableProps {
  columns: string[];
  rows: unknown[][];
  rowCount: number;
  sql?: string;
  explanation?: string;
}

export function ResultsTable({ columns, rows, rowCount, sql, explanation }: ResultsTableProps) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm">Results</CardTitle>
          <Badge variant="secondary" className="text-xs">
            {rowCount} row{rowCount !== 1 ? "s" : ""}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {sql && (
          <div className="rounded-md bg-muted p-3">
            <div className="mb-1 text-[10px] font-medium uppercase text-muted-foreground">
              Generated SQL
            </div>
            <pre className="overflow-x-auto font-mono text-xs">{sql}</pre>
          </div>
        )}

        {explanation && (
          <div className="rounded-md border p-3 text-sm leading-relaxed">
            {explanation}
          </div>
        )}

        {columns.length > 0 && (
          <ScrollArea className="max-h-96">
            <Table className="tabular-nums">
              <TableHeader>
                <TableRow>
                  {columns.map((col) => (
                    <TableHead key={col} className="text-xs font-medium">
                      {col}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row, i) => (
                  <TableRow key={i}>
                    {row.map((cell, j) => (
                      <TableCell key={j} className="text-xs">
                        {cell === null ? (
                          <span className="text-muted-foreground">NULL</span>
                        ) : (
                          String(cell)
                        )}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
}
