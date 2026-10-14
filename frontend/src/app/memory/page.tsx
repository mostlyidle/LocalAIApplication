"use client";

import { useCallback, useEffect, useState } from "react";
import { BrainCircuit, Loader2, Plus, Search, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  createMemory,
  deleteAllMemories,
  deleteMemory,
  getMemories,
  getMemorySettings,
  updateMemory,
  updateMemorySettings,
} from "@/lib/api";
import type { MemoryRecord, MemorySettings } from "@/lib/schemas";

const MEMORY_KINDS: { value: MemoryRecord["kind"]; label: string }[] = [
  { value: "fact", label: "Fact" },
  { value: "preference", label: "Preference" },
  { value: "project_decision", label: "Project decision" },
];

export default function MemoryPage() {
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [settings, setSettings] = useState<MemorySettings | null>(null);
  const [content, setContent] = useState("");
  const [kind, setKind] = useState<MemoryRecord["kind"]>("fact");
  const [projectScope, setProjectScope] = useState("");
  const [query, setQuery] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async (search = "") => {
    setLoading(true);
    setError("");
    try {
      const [memoryResult, memorySettings] = await Promise.all([
        getMemories(search),
        getMemorySettings(),
      ]);
      setMemories(memoryResult.memories);
      setSettings(memorySettings);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load account memory.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const submitMemory = async () => {
    if (!content.trim()) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      if (editingId) {
        const current = memories.find((memory) => memory.id === editingId);
        if (!current) throw new Error("This memory is no longer available. Refresh the list.");
        await updateMemory(editingId, {
          revision: current.revision,
          content: content.trim(),
          kind,
          project_scope: projectScope.trim() || null,
        });
        setNotice("Memory updated.");
      } else {
        await createMemory({
          content: content.trim(),
          kind,
          ...(projectScope.trim() ? { project_scope: projectScope.trim() } : {}),
        });
        setNotice("Memory saved to your account.");
      }
      setContent("");
      setProjectScope("");
      setKind("fact");
      setEditingId(null);
      await load(query);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save this memory.");
    } finally {
      setSaving(false);
    }
  };

  const startEditing = (memory: MemoryRecord) => {
    setEditingId(memory.id);
    setContent(memory.content);
    setKind(memory.kind);
    setProjectScope(memory.project_scope ?? "");
    setNotice("");
  };

  const handleDelete = async (memory: MemoryRecord) => {
    if (!window.confirm("Delete this saved memory? It will no longer be available to agents.")) return;
    setError("");
    try {
      await deleteMemory(memory.id, memory.revision);
      if (editingId === memory.id) cancelEdit();
      setNotice("Memory deleted.");
      await load(query);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not delete this memory.");
    }
  };

  const cancelEdit = () => {
    setEditingId(null);
    setContent("");
    setProjectScope("");
    setKind("fact");
  };

  const changeSetting = async (name: keyof MemorySettings, checked: boolean) => {
    if (!settings) return;
    const previous = settings;
    setSettings({ ...settings, [name]: checked });
    setError("");
    try {
      setSettings(await updateMemorySettings({ [name]: checked }));
    } catch (cause) {
      setSettings(previous);
      setError(cause instanceof Error ? cause.message : "Could not update memory settings.");
    }
  };

  const handleDeleteAll = async () => {
    if (!window.confirm("Delete all saved memories? This cannot be undone.")) return;
    setError("");
    try {
      await deleteAllMemories();
      if (editingId) cancelEdit();
      setNotice("All saved memories were deleted. Past-chat recall is now off.");
      await load(query);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not delete saved memories.");
    }
  };

  return (
    <div className="container mx-auto max-w-4xl space-y-6 px-4 py-6 sm:p-8">
      <header className="flex items-center gap-3">
        <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-violet-soft text-violet-ink"><BrainCircuit className="h-6 w-6" aria-hidden="true" /></span>
        <div>
          <h1 className="text-2xl font-bold">Memory</h1>
          <p className="text-sm text-muted-foreground">Review and manage facts saved to your account.</p>
        </div>
      </header>

      {error && <p role="alert" className="rounded-md border border-destructive/40 p-3 text-sm text-destructive">{error}</p>}
      {notice && <p role="status" className="rounded-md border p-3 text-sm">{notice}</p>}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Memory controls</CardTitle>
          <CardDescription>Each option is independent and starts off. Saved memories are only added when you submit them here.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {settings ? ([
            ["memory_enabled", "Use saved memories", "Allow agents to use your approved memories in new conversations."],
            ["past_chat_recall_enabled", "Search past conversations", "Allow future retrieval from your conversation history."],
          ] as const).map(([name, label, description]) => (
            <label key={name} className="flex cursor-pointer items-start justify-between gap-4 rounded-md border p-3">
              <span>
                <span className="block text-sm font-medium">{label}</span>
                <span className="block text-xs text-muted-foreground">{description}</span>
              </span>
              <input
                aria-label={label}
                type="checkbox"
                className="mt-1 h-4 w-4 accent-primary"
                checked={settings[name]}
                onChange={(event) => void changeSetting(name, event.target.checked)}
              />
            </label>
          )) : <p className="text-sm text-muted-foreground">Loading memory settings…</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{editingId ? "Edit memory" : "Remember something"}</CardTitle>
          <CardDescription>Write the exact fact or preference you want your account to remember.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="memory-kind">Type</Label>
              <Select value={kind} onValueChange={(value) => setKind(value as MemoryRecord["kind"])}>
                <SelectTrigger id="memory-kind" className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent position="popper" align="start">
                  {MEMORY_KINDS.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="memory-project">Project (optional)</Label>
              <Input id="memory-project" value={projectScope} onChange={(event) => setProjectScope(event.target.value)} maxLength={128} placeholder="e.g. Project Cedar" />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="memory-content">Memory</Label>
            <textarea id="memory-content" value={content} onChange={(event) => setContent(event.target.value)} maxLength={4000} rows={3} placeholder="e.g. I prefer concise answers with examples." className="w-full resize-y rounded-md border bg-background px-3 py-2 text-sm" />
          </div>
          <div className="flex gap-2">
            <Button onClick={() => void submitMemory()} disabled={saving || !content.trim()}>
              {saving ? <Loader2 className="animate-spin" /> : <Plus />}{editingId ? "Save changes" : "Save memory"}
            </Button>
            {editingId && <Button variant="outline" onClick={cancelEdit} disabled={saving}>Cancel</Button>}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle className="text-base">Saved memories</CardTitle>
            <CardDescription>{memories.length} shown · owned by your account</CardDescription>
          </div>
          {memories.length > 0 && <Button variant="destructive" size="sm" onClick={() => void handleDeleteAll()}><Trash2 />Delete all</Button>}
        </CardHeader>
        <CardContent className="space-y-3">
          <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); void load(query); }}>
            <Input aria-label="Search memories" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search saved memories" />
            <Button type="submit" variant="outline" aria-label="Search"><Search /></Button>
          </form>
          {loading ? <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Loading memories…</p> : memories.length === 0 ? (
            <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">No saved memories yet.</p>
          ) : memories.map((memory) => (
            <article key={memory.id} className="rounded-md border p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <p className="whitespace-pre-wrap text-sm">{memory.content}</p>
                  <p className="mt-2 text-xs text-muted-foreground">
                    {MEMORY_KINDS.find((option) => option.value === memory.kind)?.label}
                    {memory.project_scope ? ` · ${memory.project_scope}` : ""}
                    {` · updated ${new Date(memory.updated_at).toLocaleDateString()}`}
                  </p>
                  {memory.source_conversation_id && <p className="mt-1 break-all text-[10px] text-muted-foreground">Source conversation: {memory.source_conversation_id}</p>}
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" onClick={() => startEditing(memory)}>Edit</Button>
                  <Button variant="ghost" size="sm" onClick={() => void handleDelete(memory)} aria-label={`Delete memory: ${memory.content.slice(0, 40)}`}><Trash2 /></Button>
                </div>
              </div>
            </article>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
