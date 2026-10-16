"use client";

import { useState, type FormEvent } from "react";
import { Play, Loader2, Sparkles, Terminal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface QueryEditorProps {
  onNaturalLanguageQuery: (query: string) => Promise<void>;
  onRawSQLExecute: (sql: string) => Promise<void>;
  isLoading: boolean;
  rawSQL?: string;
  onRawSQLChange?: (sql: string) => void;
  activeTab?: "natural" | "sql";
  onActiveTabChange?: (tab: "natural" | "sql") => void;
}

export function QueryEditor({
  onNaturalLanguageQuery,
  onRawSQLExecute,
  isLoading,
  rawSQL: rawSQLProp,
  onRawSQLChange,
  activeTab: activeTabProp,
  onActiveTabChange,
}: QueryEditorProps) {
  const [nlQuery, setNlQuery] = useState("");
  const [localRawSQL, setLocalRawSQL] = useState("");
  const [localActiveTab, setLocalActiveTab] = useState<"natural" | "sql">("natural");
  const rawSQL = rawSQLProp ?? localRawSQL;
  const updateRawSQL = onRawSQLChange ?? setLocalRawSQL;
  const activeTab = activeTabProp ?? localActiveTab;
  const updateActiveTab = onActiveTabChange ?? setLocalActiveTab;

  const handleNLSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!nlQuery.trim() || isLoading) return;
    await onNaturalLanguageQuery(nlQuery.trim());
  };

  const handleSQLSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!rawSQL.trim() || isLoading) return;
    await onRawSQLExecute(rawSQL.trim());
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm">Query</CardTitle>
      </CardHeader>
      <CardContent>
        <Tabs value={activeTab} onValueChange={(value) => updateActiveTab(value as "natural" | "sql")}>
          <TabsList className="mb-3">
            <TabsTrigger value="natural" className="text-xs">
              <Sparkles className="mr-1.5 h-3 w-3" />
              Natural Language
            </TabsTrigger>
            <TabsTrigger value="sql" className="text-xs">
              <Terminal className="mr-1.5 h-3 w-3" />
              Raw SQL
            </TabsTrigger>
          </TabsList>

          <TabsContent value="natural">
            <form onSubmit={handleNLSubmit} className="space-y-3">
              <Textarea
                aria-label="Question for the SQL agent"
                value={nlQuery}
                onChange={(e) => setNlQuery(e.target.value)}
                placeholder="e.g. Show me the top 5 customers by total spending"
                className="min-h-[80px] resize-none font-sans text-sm"
                rows={3}
              />
              <Button type="submit" size="sm" disabled={!nlQuery.trim() || isLoading}>
                {isLoading ? (
                  <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                ) : (
                  <Sparkles className="mr-2 h-3 w-3" />
                )}
                Ask AI
              </Button>
            </form>
          </TabsContent>

          <TabsContent value="sql">
            <form onSubmit={handleSQLSubmit} className="space-y-3">
              <Textarea
                aria-label="SQL query"
                value={rawSQL}
                onChange={(e) => updateRawSQL(e.target.value)}
                placeholder="SELECT * FROM customers LIMIT 10;"
                className="min-h-[80px] resize-none font-mono text-sm"
                rows={3}
              />
              <Button type="submit" size="sm" disabled={!rawSQL.trim() || isLoading}>
                {isLoading ? (
                  <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                ) : (
                  <Play className="mr-2 h-3 w-3" />
                )}
                Execute
              </Button>
            </form>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
