"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Search, Trash2, Database, Loader2, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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

export default function RAGPage() {
  const [query, setQuery] = useState("");
  const [agentName, setAgentName] = useState("rag");
  const [selectedCollection, setSelectedCollection] = useState("");
  const [selectedContainer, setSelectedContainer] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [containers, setContainers] = useState<RAGContainer[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [isLoadingCollections, setIsLoadingCollections] = useState(true);
  const [collectionsError, setCollectionsError] = useState("");
  const [containersError, setContainersError] = useState("");
  const [error, setError] = useState<string | null>(null);

  const loadCollections = useCallback(async () => {
    try {
      const data = await api.getRAGCollections();
      const next = ((data.collections ?? []) as Collection[])
        .filter((collection) => collection.name !== "localai_rag_e2e");
      setCollections(next);
      setCollectionsError("");
      setSelectedCollection((current) => current || next[0]?.name || "");
    } catch (err) {
      setCollectionsError(err instanceof Error ? err.message : "Could not load collections.");
    } finally {
      setIsLoadingCollections(false);
    }
  }, []);

  const loadContainers = useCallback(async () => {
    try {
      const data = await api.getRAGContainers();
      setContainers(data);
      setContainersError("");
      setSelectedContainer((current) => current || data[0]?.name || "");
      setSelectedCollection((current) => current || data[0]?.name || "");
    } catch (err) {
      setContainersError(err instanceof Error ? err.message : "Could not load containers.");
    }
  }, []);

  useEffect(() => {
    loadCollections();
    loadContainers();
  }, [loadCollections, loadContainers]);

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
      if (selectedCollection === name) {
        setSelectedCollection("");
        setResults([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  return (
    <div className="container mx-auto max-w-5xl px-4 py-6 sm:p-8">
      <div className="mb-6 flex items-center gap-3">
        <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-sky-soft text-sky-ink"><Search className="h-6 w-6" aria-hidden="true" /></span>
        <div><h1 className="text-2xl font-bold">RAG Search</h1><p className="mt-1 text-sm text-muted-foreground">Find the dots. Connect the ideas.</p></div>
      </div>

      <Tabs defaultValue="search" className="space-y-5">
        <TabsList className="grid h-auto w-full max-w-sm grid-cols-2">
          <TabsTrigger value="search">Search</TabsTrigger>
          <TabsTrigger value="sources">Files &amp; indexes</TabsTrigger>
        </TabsList>

        {containersError && (
          <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
            <p>Could not load RAG containers: {containersError}</p>
            <Button type="button" size="sm" variant="outline" onClick={() => void loadContainers()}>
              Retry
            </Button>
          </div>
        )}

        <TabsContent value="sources" className="space-y-4">
          <div className="max-w-3xl">
            <h2 className="text-lg font-semibold">Manage indexed files</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Choose a private container to see its files and indexing status. Newly added files are staged;
              load them before they can appear in search results.
            </p>
          </div>
          <ContainerManager
            containers={containers}
            selectedName={selectedContainer}
            onSelect={selectContainer}
            onRefresh={refreshRag}
          />
        </TabsContent>

        <TabsContent value="search">
          <div className="grid min-w-0 gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2 space-y-6">
              {/* Search form */}
              <Card>
                <CardContent className="pt-6">
                  <form onSubmit={handleSearch} className="grid gap-3 sm:grid-cols-2">
                    <label htmlFor="rag-query" className="text-sm font-semibold sm:col-span-2">Search your knowledge base</label>
                    <Input
                      id="rag-query"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      placeholder="Search your knowledge base..."
                      className="min-w-0 w-full sm:col-span-2"
                    />
                    <Select
                      value={selectedCollection}
                      onValueChange={(value) => {
                        setSelectedCollection(value);
                        if (containers.some((container) => container.name === value)) {
                          setSelectedContainer(value);
                        }
                      }}
                    >
                      <SelectTrigger aria-label="Search index" className="w-full min-w-0 [&_[data-slot=select-value]]:min-w-0 [&_[data-slot=select-value]]:overflow-hidden"><SelectValue placeholder="Select an index" /></SelectTrigger>
                      <SelectContent position="popper" align="start">
                      {containers.length > 0 && (
                        <SelectGroup>
                          <SelectLabel>Private containers</SelectLabel>
                          {containers.map((container) => (
                            <SelectItem key={container.name} value={container.name}>
                              <span className="min-w-0 whitespace-normal break-words [overflow-wrap:anywhere]">{container.display_name}</span>
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      )}
                      {searchableCollections.length > 0 && (
                        <SelectGroup>
                          <SelectLabel>Existing collections</SelectLabel>
                          {searchableCollections.map((collection) => (
                            <SelectItem key={collection.name} value={collection.name}>
                              <span className="min-w-0 whitespace-normal break-words [overflow-wrap:anywhere]">{collection.name}</span>
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      )}
                      </SelectContent>
                    </Select>
                    <Select value={agentName} onValueChange={setAgentName}>
                      <SelectTrigger aria-label="Retrieval profile" className="w-full min-w-0"><SelectValue /></SelectTrigger>
                      <SelectContent position="popper" align="start">
                        <SelectItem value="rag">Hybrid retrieval</SelectItem>
                        <SelectItem value="rag_v2">Hybrid + query rewrites</SelectItem>
                      </SelectContent>
                    </Select>
                    <Button className="sm:col-span-2 sm:justify-self-start" type="submit" disabled={!query.trim() || !selectedCollection || isSearching}>
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
                <Card className="min-w-0 overflow-hidden">
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
                          <div key={i} className="min-w-0 space-y-2 rounded-md border p-3">
                            <div className="flex min-w-0 items-start justify-between gap-3">
                              <div className="flex min-w-0 items-center gap-2 text-xs">
                                <FileText className="h-3 w-3 text-muted-foreground" />
                                <span className="min-w-0 break-all font-medium">
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
                            <p className="break-words text-sm leading-relaxed [overflow-wrap:anywhere]">{result.content}</p>
                          </div>
                        ))}
                      </div>
                    </ScrollArea>
                  </CardContent>
                </Card>
              )}

              {results.length === 0 && !isSearching && query && (
                <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
                  No results found. Try a different query or add files to an index first.
                </div>
              )}
            </div>

            {/* Collections sidebar */}
            <div className="min-w-0">
              <Card>
                <CardHeader className="pb-3">
                  <div className="flex items-center gap-2">
                    <Database className="h-4 w-4 text-muted-foreground" />
                  <CardTitle className="text-sm">Other collections</CardTitle>
                  </div>
                </CardHeader>
                <CardContent>
                  {isLoadingCollections ? (
                    <div className="space-y-2">
                      <Skeleton className="h-8 w-full" />
                      <Skeleton className="h-8 w-full" />
                    </div>
                  ) : collectionsError ? (
                    <div role="alert" className="space-y-3 rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
                      <p>Could not load collections: {collectionsError}</p>
                      <Button type="button" size="sm" variant="outline" onClick={() => void loadCollections()}>
                        Retry
                      </Button>
                    </div>
                  ) : searchableCollections.length === 0 ? (
                    <p className="text-xs text-muted-foreground">
                      No additional collections. Manage private indexes in Files &amp; indexes.
                    </p>
                  ) : (
                    <div className="space-y-2">
                      {searchableCollections.map((col) => (
                        <div
                          key={col.name}
                          className="flex min-w-0 items-center justify-between gap-3 rounded-md border px-3 py-2"
                        >
                          <div className="min-w-0">
                            <div className="break-all text-xs font-medium">{col.name}</div>
                            <div className="text-[10px] text-muted-foreground">
                              {col.count} chunk{col.count !== 1 ? "s" : ""}
                            </div>
                          </div>
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={`Delete ${col.name} collection`}
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
        </TabsContent>
      </Tabs>
    </div>
  );
}
