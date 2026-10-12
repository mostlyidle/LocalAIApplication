"use client";

import { useCallback, useEffect, useState } from "react";
import { Database } from "lucide-react";
import * as api from "@/lib/api";
import { QueryEditor } from "@/components/sql/QueryEditor";
import { ResultsTable } from "@/components/sql/ResultsTable";
import { SchemaBrowser } from "@/components/sql/SchemaBrowser";

interface QueryResult {
  columns: string[];
  rows: unknown[][];
  rowCount: number;
  sql?: string;
  explanation?: string;
  error?: string;
}

interface SQLConnection {
  name: string;
  url: string;
}

export default function SQLPage() {
  const [result, setResult] = useState<QueryResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connections, setConnections] = useState<SQLConnection[]>([]);
  const [selectedDb, setSelectedDb] = useState("default");

  const loadConnections = useCallback(async () => {
    try {
      const data = await api.getSQLConnections();
      const conns = (data.connections ?? data ?? []) as SQLConnection[];
      setConnections(conns);
    } catch {
      // Non-critical — fall back to default
    }
  }, []);

  useEffect(() => {
    loadConnections();
  }, [loadConnections]);

  const handleNLQuery = async (query: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.querySQL(query, selectedDb);
      setResult({
        columns: data.results?.columns ?? [],
        rows: data.results?.rows ?? [],
        rowCount: data.results?.row_count ?? 0,
        sql: data.sql,
        explanation: data.explanation,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Query failed");
      setResult(null);
    } finally {
      setIsLoading(false);
    }
  };

  const handleRawSQL = async (sql: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.executeSQL(sql, selectedDb);
      setResult({
        columns: data.columns ?? [],
        rows: data.rows ?? [],
        rowCount: data.row_count ?? 0,
        sql,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Execution failed");
      setResult(null);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="container mx-auto max-w-6xl px-4 py-6 sm:p-8">
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-mint-soft text-mint-ink"><Database className="h-6 w-6" aria-hidden="true" /></span>
        <div><h1 className="text-2xl font-bold">SQL Agent</h1><p className="mt-1 text-sm text-muted-foreground">Good questions. Useful data.</p></div>
        {connections.length > 0 && (
          <select
            value={selectedDb}
            onChange={(e) => setSelectedDb(e.target.value)}
            className="ml-auto min-h-11 max-w-full rounded-xl border border-input bg-card px-3 py-1.5 text-base sm:text-sm"
            aria-label="Database connection"
          >
            <option value="default">default</option>
            {connections.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name}
              </option>
            ))}
          </select>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-6">
          <QueryEditor
            onNaturalLanguageQuery={handleNLQuery}
            onRawSQLExecute={handleRawSQL}
            isLoading={isLoading}
          />

          {error && (
            <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}

          {result && (
            <ResultsTable
              columns={result.columns}
              rows={result.rows}
              rowCount={result.rowCount}
              sql={result.sql}
              explanation={result.explanation}
            />
          )}
        </div>

        <div>
          <SchemaBrowser database={selectedDb} />
        </div>
      </div>
    </div>
  );
}
