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
}

export function SchemaBrowser({ database }: SchemaBrowserProps = {}) {
  const [tables, setTables] = useState<TableSchema[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      setIsLoading(true);
      setError(null);
      try {
        const data = await api.getSQLSchema(database);
        setTables(data.tables ?? []);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load schema");
      } finally {
        setIsLoading(false);
      }
    }
    load();
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
        ) : (
          <ScrollArea className="max-h-96">
            <div className="space-y-1">
              {tables.map((table) => (
                <div key={table.name}>
                  <button
                    onClick={() => toggleTable(table.name)}
                    className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-accent"
                  >
                    {expanded.has(table.name) ? (
                      <ChevronDown className="h-3 w-3" />
                    ) : (
                      <ChevronRight className="h-3 w-3" />
                    )}
                    <Table2 className="h-3 w-3 text-muted-foreground" />
                    <span className="font-mono font-medium">{table.name}</span>
                    <Badge variant="outline" className="ml-auto text-[10px]">
                      {table.columns.length} cols
                    </Badge>
                  </button>
                  {expanded.has(table.name) && (
                    <div className="ml-6 space-y-0.5 pb-1 pl-2 border-l">
                      {table.columns.map((col) => (
                        <div
                          key={col.name}
                          className="flex items-center gap-2 px-2 py-1 text-[11px]"
                        >
                          {col.primary_key && (
                            <Key className="h-2.5 w-2.5 text-amber-500" />
                          )}
                          <span className={cn("font-mono", col.primary_key && "font-semibold")}>
                            {col.name}
                          </span>
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
