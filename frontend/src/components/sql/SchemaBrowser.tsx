"use client";

import { useEffect, useState } from "react";
import { Database, Table2, Key, Loader2, ChevronRight, ChevronDown } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import * as api from "@/lib/api";

interface TableSchema {
  name: string;
  columns: { name: string; type: string; nullable: boolean; primary_key: boolean }[];
}

interface SchemaBrowserProps {
  database?: string;
  onInsertText?: (text: string) => void;
}

export function SchemaBrowser({ database, onInsertText }: SchemaBrowserProps = {}) {
  const [tables, setTables] = useState<TableSchema[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function load() {
      setIsLoading(true);
      setError(null);
      setTables([]);
      try {
        const data = await api.getSQLSchema(database);
        if (active) setTables(data.tables ?? []);
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Failed to load schema");
      } finally {
        if (active) setIsLoading(false);
      }
    }
    void load();
    return () => { active = false; };
  }, [database]);

  const toggleTable = (name: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4 text-muted-foreground" />
          <CardTitle className="text-sm">Schema</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading schema...
          </div>
        ) : error ? (
          <p className="text-xs text-destructive">{error}</p>
        ) : tables.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No tables found in this database. Select a database with tables to browse its schema.
          </p>
        ) : (
          <ScrollArea className="max-h-96">
            <div className="space-y-1">
              {tables.map((table) => (
                <div key={table.name}>
                  <div className="flex items-center gap-1 rounded px-1 hover:bg-accent">
                    <button type="button" onClick={() => toggleTable(table.name)} aria-label={`${expanded.has(table.name) ? "Collapse" : "Expand"} ${table.name}`} className="grid size-7 shrink-0 place-items-center rounded">
                    {expanded.has(table.name) ? (
                      <ChevronDown className="h-3 w-3" />
                    ) : (
                      <ChevronRight className="h-3 w-3" />
                    )}
                    </button>
                    <Table2 className="h-3 w-3 text-muted-foreground" />
                    <button type="button" onClick={() => { toggleTable(table.name); onInsertText?.(table.name); }} className="min-h-9 text-left font-mono text-xs font-medium hover:underline">
                      {table.name}
                    </button>
                    <Badge variant="outline" className="ml-auto text-[10px]">
                      {table.columns.length} cols
                    </Badge>
                  </div>
                  {expanded.has(table.name) && (
                    <div className="ml-6 space-y-0.5 pb-1 pl-2 border-l">
                      {table.columns.map((col) => (
                        <div key={col.name} className="flex items-center gap-2 px-2 py-1 text-[11px]">
                          {col.primary_key && (
                            <Key className="h-2.5 w-2.5 text-peach-ink" />
                          )}
                          <button type="button" onClick={() => onInsertText?.(col.name)} className={cn("min-h-7 font-mono hover:underline", col.primary_key && "font-semibold")}>
                            {col.name}
                          </button>
                          <span className="text-muted-foreground">{col.type}</span>
                          {col.nullable && (
                            <span className="text-muted-foreground/50">nullable</span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
}
