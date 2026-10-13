"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Search, Trash2, Database, Loader2, FileText, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { ContainerManager } from "@/components/rag/ContainerManager";
import * as api from "@/lib/api";
import type { RAGContainer } from "@/lib/api";

interface SearchResult {
  content: string;
  score: number;
  score_type?: string;
  metadata: Record<string, unknown>;
}

interface Collection {
  name: string;
  count: number;
}

interface DocumentItem {
  id: string;
  filename: string;
  format: string;
  size_bytes: number;
  status: string;
}

export default function RAGPage() {
  const [query, setQuery] = useState("");
  const [agentName, setAgentName] = useState("rag");
  const [selectedCollection, setSelectedCollection] = useState("");
  const [selectedContainer, setSelectedContainer] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [containers, setContainers] = useState<RAGContainer[]>([]);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [isLoadingCollections, setIsLoadingCollections] = useState(true);
  const [isLoadingDocuments, setIsLoadingDocuments] = useState(true);
  const [ingestingIds, setIngestingIds] = useState<Set<string>>(new Set());
  const [ingestCollection, setIngestCollection] = useState("documents");
  const [error, setError] = useState<string | null>(null);

  const loadCollections = useCallback(async () => {
    try {
      const data = await api.getRAGCollections();
      const next = (data.collections ?? []) as Collection[];
      setCollections(next);
      setSelectedCollection((current) => current || next[0]?.name || "");
    } catch (err) {
      console.error("Failed to load collections:", err);
    } finally {
      setIsLoadingCollections(false);
    }
  }, []);

  const loadContainers = useCallback(async () => {
    try {
      const data = await api.getRAGContainers();
      setContainers(data);
      setSelectedContainer((current) => current || data[0]?.name || "");
      setSelectedCollection((current) => current || data[0]?.name || "");
    } catch (err) {
      console.error("Failed to load containers:", err);
    }
  }, []);

  const loadDocuments = useCallback(async () => {
    try {
      const data = await api.getDocuments();
      setDocuments((data.documents ?? data ?? []) as DocumentItem[]);
    } catch (err) {
      console.error("Failed to load documents:", err);
    } finally {
      setIsLoadingDocuments(false);
    }
  }, []);

  useEffect(() => {
    loadCollections();
    loadContainers();
    loadDocuments();
  }, [loadCollections, loadContainers, loadDocuments]);

  const refreshRag = useCallback(async () => {
    await Promise.all([loadContainers(), loadCollections()]);
  }, [loadCollections, loadContainers]);

  const handleSearch = async (e: FormEvent) => {
    e.preventDefault();
    if (!query.trim() || isSearching) return;
    setIsSearching(true);
    setError(null);
    try {
      const data = await api.searchRAG(query.trim(), selectedCollection, undefined, agentName);
      setResults((data.results ?? []) as SearchResult[]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
      setResults([]);
    } finally {
      setIsSearching(false);
    }
  };

  const selectContainer = (name: string) => {
    setSelectedContainer(name);
    if (name) setSelectedCollection(name);
    else setSelectedCollection((current) => current === selectedContainer ? "" : current);
  };

  const searchableCollections = collections.filter(
    (collection) => !containers.some((container) => container.name === collection.name),
  );

  const handleDeleteCollection = async (name: string) => {
    try {
      await api.deleteRAGCollection(name);
      setCollections((prev) => prev.filter((c) => c.name !== name));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  const handleIngest = async (documentId: string) => {
    setIngestingIds((prev) => new Set(prev).add(documentId));
    setError(null);
    try {
      await api.ingestRAG(documentId, ingestCollection || undefined);
      // Refresh collections to show updated counts
      await loadCollections();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ingest failed");
    } finally {
      setIngestingIds((prev) => {
        const next = new Set(prev);
        next.delete(documentId);
        return next;
      });
    }
  };

  return (
    <div className="container mx-auto max-w-5xl px-4 py-6 sm:p-8">
      <div className="mb-6 flex items-center gap-3">
        <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-sky-soft text-sky-ink"><Search className="h-6 w-6" aria-hidden="true" /></span>
        <div><h1 className="text-2xl font-bold">RAG Search</h1><p className="mt-1 text-sm text-muted-foreground">Find the dots. Connect the ideas.</p></div>
      </div>

      <div className="mb-6">
        <ContainerManager
          containers={containers}
          selectedName={selectedContainer}
          onSelect={selectContainer}
          onRefresh={refreshRag}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-6">
          {/* Search form */}
          <Card>
            <CardContent className="pt-6">
              <form onSubmit={handleSearch} className="flex flex-wrap gap-2">
                <label htmlFor="rag-query" className="basis-full text-sm font-semibold">Search your knowledge base</label>
                <Input
                  id="rag-query"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search your knowledge base..."
                  className="min-w-0 basis-full sm:basis-48 sm:flex-1"
                />
                <select
                  aria-label="Search index"
                  value={selectedCollection}
                  onChange={(event) => {
                    setSelectedCollection(event.target.value);
                    if (containers.some((container) => container.name === event.target.value)) {
                      setSelectedContainer(event.target.value);
                    }
                  }}
                  className="h-11 max-w-full rounded-xl border border-input bg-card px-3 text-base sm:text-sm"
                >
                  <option value="" disabled>Select an index</option>
                  {containers.length > 0 && (
                    <optgroup label="Private containers">
                      {containers.map((container) => (
                        <option key={container.name} value={container.name}>{container.display_name}</option>
                      ))}
                    </optgroup>
                  )}
                  {searchableCollections.length > 0 && (
                    <optgroup label="Existing collections">
                      {searchableCollections.map((collection) => (
                        <option key={collection.name} value={collection.name}>{collection.name}</option>
                      ))}
                    </optgroup>
                  )}
                </select>
                <select
                  aria-label="Retrieval profile"
                  value={agentName}
                  onChange={(e) => setAgentName(e.target.value)}
                  className="h-11 max-w-full rounded-xl border border-input bg-card px-3 text-base sm:text-sm"
                >
                  <option value="rag">Hybrid retrieval</option>
                  <option value="rag_v2">Hybrid + query rewrites</option>
                </select>
                  <Button type="submit" disabled={!query.trim() || !selectedCollection || isSearching}>
                  {isSearching ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Search className="mr-2 h-4 w-4" />
                  )}
                  Search
                </Button>
              </form>
            </CardContent>
          </Card>

          {error && (
            <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}

          {/* Results */}
          {results.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm">Results</CardTitle>
                  <Badge variant="secondary">{results.length} found</Badge>
                </div>
              </CardHeader>
              <CardContent>
                <ScrollArea className="max-h-[500px]">
                  <div className="space-y-4">
                    {results.map((result, i) => (
                      <div key={i} className="space-y-2 rounded-md border p-3">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2 text-xs">
                            <FileText className="h-3 w-3 text-muted-foreground" />
                            <span className="font-medium">
                              {String(result.metadata.source ?? "Unknown")}
                            </span>
                            {result.metadata.page != null && (
                              <span className="text-muted-foreground">
                                p.{String(result.metadata.page)}
                              </span>
                            )}
                          </div>
                          <Badge
                            variant={result.score_type === "rrf" ? "secondary" : result.score > 0.8 ? "default" : "secondary"}
                            className="text-[10px]"
                          >
                            {result.score_type === "rrf"
                              ? `RRF ${result.score.toFixed(4)}`
                              : `${(result.score * 100).toFixed(1)}%`}
                          </Badge>
                        </div>
                        <p className="text-sm leading-relaxed">{result.content}</p>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              </CardContent>
            </Card>
          )}

          {results.length === 0 && !isSearching && query && (
            <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
              No results found. Try a different query or ingest some documents first.
            </div>
          )}

          {/* Ingest documents section */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center gap-2">
                <Upload className="h-4 w-4 text-muted-foreground" />
                <CardTitle className="text-sm">Ingest Documents</CardTitle>
              </div>
            </CardHeader>
            <CardContent>
              <div className="mb-3">
                <label className="mb-1 block text-xs text-muted-foreground">
                  Target collection
                </label>
                <Input
                  value={ingestCollection}
                  onChange={(e) => setIngestCollection(e.target.value)}
                  placeholder="documents"
                  className="max-w-xs text-xs"
                />
              </div>
              <Separator className="my-3" />
              {isLoadingDocuments ? (
                <div className="space-y-2">
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-full" />
                </div>
              ) : documents.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No documents uploaded yet. Upload documents on the Documents page first.
                </p>
              ) : (
                <ScrollArea className="max-h-64">
                  <div className="space-y-2">
                    {documents.map((doc) => (
                      <div
                        key={doc.id}
                        className="flex items-center justify-between rounded-md border px-3 py-2"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 text-xs">
                            <FileText className="h-3 w-3 shrink-0 text-muted-foreground" />
                            <span className="truncate font-medium">{doc.filename}</span>
                          </div>
                          <div className="ml-5 text-[10px] text-muted-foreground">
                            {doc.format} &middot;{" "}
                            {(doc.size_bytes / 1024).toFixed(1)} KB
                          </div>
                        </div>
                        <Button
                          variant="outline"
                          size="sm"
                          className="ml-2 shrink-0 text-xs"
                          disabled={ingestingIds.has(doc.id)}
                          onClick={() => handleIngest(doc.id)}
                        >
                          {ingestingIds.has(doc.id) ? (
                            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                          ) : (
                            <Upload className="mr-1 h-3 w-3" />
                          )}
                          Ingest
                        </Button>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Collections sidebar */}
        <div>
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center gap-2">
                <Database className="h-4 w-4 text-muted-foreground" />
                <CardTitle className="text-sm">Collections</CardTitle>
              </div>
            </CardHeader>
            <CardContent>
              {isLoadingCollections ? (
                <div className="space-y-2">
                  <Skeleton className="h-8 w-full" />
                  <Skeleton className="h-8 w-full" />
                </div>
              ) : searchableCollections.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No collections yet. Ingest documents via the Documents page or API.
                </p>
              ) : (
                <div className="space-y-2">
                  {searchableCollections.map((col) => (
                    <div
                      key={col.name}
                      className="flex items-center justify-between rounded-md border px-3 py-2"
                    >
                      <div>
                        <div className="text-xs font-medium">{col.name}</div>
                        <div className="text-[10px] text-muted-foreground">
                          {col.count} document{col.count !== 1 ? "s" : ""}
                        </div>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 text-muted-foreground hover:text-destructive"
                        onClick={() => handleDeleteCollection(col.name)}
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
