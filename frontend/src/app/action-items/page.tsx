"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, CircleCheck, ListTodo, Loader2, Pencil, Plus, Sparkles, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  createActionItem,
  deleteActionItem,
  getActionItems,
  getConversations,
  getDocuments,
  getMeetings,
  proposeActionItems,
  updateActionItem,
} from "@/lib/api";
import type { ActionItemRecord, ActionItemSuggestion } from "@/lib/schemas";

const statusLabels: Record<ActionItemRecord["status"], string> = {
  next: "To do",
  in_progress: "In progress",
  done: "Done",
};
type PlannerSourceType = "chat" | "meeting" | "document";
interface PlannerSource { id: string; type: PlannerSourceType; title: string }
const CONVERSATION_PAGE_SIZE = 50;
const CONVERSATION_PAGE_LOOKAHEAD = 1;

export default function ActionItemsPage() {
  const [items, setItems] = useState<ActionItemRecord[]>([]);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<ActionItemRecord["priority"]>("normal");
  const [dueDate, setDueDate] = useState("");
  const [editing, setEditing] = useState<ActionItemRecord | null>(null);
  const [sources, setSources] = useState<PlannerSource[]>([]);
  const [conversationOffset, setConversationOffset] = useState(0);
  const [hasMoreConversations, setHasMoreConversations] = useState(false);
  const [loadingOlderConversations, setLoadingOlderConversations] = useState(false);
  const [sourceType, setSourceType] = useState<PlannerSourceType>("chat");
  const [sourceId, setSourceId] = useState("");
  const [suggestions, setSuggestions] = useState<ActionItemSuggestion[]>([]);
  const [proposalSource, setProposalSource] = useState<PlannerSource | null>(null);
  const [proposing, setProposing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [actionItems, conversations, documents, meetings] = await Promise.all([
        getActionItems(),
        getConversations(CONVERSATION_PAGE_SIZE + CONVERSATION_PAGE_LOOKAHEAD),
        getDocuments(),
        getMeetings(),
      ]);
      setItems(actionItems.items);
      const firstConversations = conversations.conversations.slice(0, CONVERSATION_PAGE_SIZE);
      setConversationOffset(firstConversations.length);
      setHasMoreConversations(conversations.conversations.length > CONVERSATION_PAGE_SIZE);
      setSources([
        ...firstConversations.map((conversation) => ({
          id: conversation.id, type: "chat" as const, title: conversation.title,
        })),
        ...documents.documents.map((document) => ({
          id: document.id, type: "document" as const, title: document.filename,
        })),
        ...meetings.filter((meeting) => meeting.status !== "active").map((meeting) => ({
          id: meeting.id, type: "meeting" as const,
          title: `Meeting · ${new Date(meeting.created_at).toLocaleDateString()}`,
        })),
      ]);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load action items.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const refreshItems = async () => {
    try {
      const actionItems = await getActionItems();
      setItems(actionItems.items);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load action items.");
    }
  };

  const loadOlderConversations = async () => {
    setLoadingOlderConversations(true);
    try {
      const page = await getConversations(
        CONVERSATION_PAGE_SIZE + CONVERSATION_PAGE_LOOKAHEAD,
        conversationOffset,
      );
      const pageConversations = page.conversations.slice(0, CONVERSATION_PAGE_SIZE);
      setSources((current) => {
        const existingChatIds = new Set(
          current.filter((source) => source.type === "chat").map((source) => source.id),
        );
        const newConversations = pageConversations.filter((conversation) => {
          if (existingChatIds.has(conversation.id)) return false;
          existingChatIds.add(conversation.id);
          return true;
        });
        return [
          ...current,
          ...newConversations.map((conversation) => ({
            id: conversation.id, type: "chat" as const, title: conversation.title,
          })),
        ];
      });
      setConversationOffset((current) => current + pageConversations.length);
      setHasMoreConversations(page.conversations.length > CONVERSATION_PAGE_SIZE);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load older chats.");
    } finally {
      setLoadingOlderConversations(false);
    }
  };

  const resetForm = () => {
    setEditing(null);
    setTitle("");
    setDescription("");
    setPriority("normal");
    setDueDate("");
  };

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!title.trim()) return;
    setSaving(true);
    setError("");
    try {
      if (editing) {
        await updateActionItem(editing.id, {
          revision: editing.revision,
          title: title.trim(),
          description: description.trim() || null,
          priority,
          due_date: dueDate || null,
        });
      } else {
        await createActionItem({
          title: title.trim(),
          ...(description.trim() ? { description: description.trim() } : {}),
          priority,
          ...(dueDate ? { due_date: dueDate } : {}),
        });
      }
      resetForm();
      await refreshItems();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save this action item.");
    } finally {
      setSaving(false);
    }
  };

  const edit = (item: ActionItemRecord) => {
    setEditing(item);
    setTitle(item.title);
    setDescription(item.description ?? "");
    setPriority(item.priority);
    setDueDate(item.due_date ?? "");
  };

  const changeStatus = async (item: ActionItemRecord, status: ActionItemRecord["status"]) => {
    try {
      await updateActionItem(item.id, { revision: item.revision, status });
      await refreshItems();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not update this action item.");
    }
  };

  const remove = async (item: ActionItemRecord) => {
    try {
      await deleteActionItem(item.id);
      await refreshItems();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not delete this action item.");
    }
  };

  const runPlanner = async () => {
    if (!sourceId) return;
    setProposing(true);
    setError("");
    try {
      const result = await proposeActionItems({ source_type: sourceType, source_id: sourceId });
      setProposalSource({ id: result.source_id, type: result.source_type, title: result.source_title });
      setSuggestions(result.suggestions);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create suggestions.");
    } finally {
      setProposing(false);
    }
  };

  const acceptSuggestion = async (suggestion: ActionItemSuggestion) => {
    if (!proposalSource || saving) return;
    setSaving(true);
    try {
      await createActionItem({
        title: suggestion.title,
        ...(suggestion.description ? { description: suggestion.description } : {}),
        priority: suggestion.priority,
        ...(suggestion.due_date ? { due_date: suggestion.due_date } : {}),
        source_type: proposalSource.type,
        source_id: proposalSource.id,
        source_quote: suggestion.source_quote,
      });
      setSuggestions((current) => current.filter((item) => item !== suggestion));
      await refreshItems();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save this suggestion.");
    } finally {
      setSaving(false);
    }
  };

  const ignoreSuggestion = (index: number) => {
    setSuggestions((current) => current.filter((_, i) => i !== index));
  };

  const availableSources = sources.filter((source) => source.type === sourceType);

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-6 sm:px-8 sm:py-10">
      <section className="brand-panel rounded-3xl border p-6 sm:p-8">
        <div className="flex items-center gap-4">
          <span className="grid size-12 place-items-center rounded-2xl bg-violet-soft text-violet-ink"><ListTodo aria-hidden="true" /></span>
          <div>
            <h1 className="text-2xl font-bold">Action planner</h1>
            <p className="mt-1 text-sm text-muted-foreground">Keep your next steps in one calm, private place.</p>
          </div>
        </div>
      </section>

      <Card className="rounded-2xl">
        <CardHeader>
          <CardTitle>{editing ? "Edit action item" : "Add an action item"}</CardTitle>
          <CardDescription>Nothing is saved until you add it here or accept an agent suggestion.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={(event) => void submit(event)} className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2 sm:col-span-2"><Label htmlFor="action-title">Title</Label><Input id="action-title" value={title} maxLength={300} onChange={(event) => setTitle(event.target.value)} required /></div>
            <div className="space-y-2 sm:col-span-2"><Label htmlFor="action-description">Details</Label><textarea id="action-description" value={description} maxLength={4000} onChange={(event) => setDescription(event.target.value)} rows={3} className="w-full rounded-md border bg-background px-3 py-2 text-sm" /></div>
            <div className="space-y-2"><Label htmlFor="action-priority">Priority</Label><Select value={priority} onValueChange={(value) => setPriority(value as ActionItemRecord["priority"])}><SelectTrigger id="action-priority" className="w-full"><SelectValue /></SelectTrigger><SelectContent position="popper" align="start"><SelectItem value="low">Low</SelectItem><SelectItem value="normal">Normal</SelectItem><SelectItem value="high">High</SelectItem></SelectContent></Select></div>
            <div className="space-y-2"><Label htmlFor="action-due-date">Due date</Label><Input id="action-due-date" type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} /></div>
            {error && <p role="alert" className="text-sm text-destructive sm:col-span-2">{error}</p>}
            <div className="flex gap-2 sm:col-span-2">
              <Button type="submit" disabled={saving || !title.trim()}>{saving ? <Loader2 className="animate-spin" /> : editing ? <Check /> : <Plus />}{editing ? "Save changes" : "Add to planner"}</Button>
              {editing && <Button type="button" variant="outline" onClick={resetForm}>Cancel</Button>}
            </div>
          </form>
        </CardContent>
      </Card>

      <Card className="rounded-2xl">
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Sparkles className="size-5 text-primary" /> Find next steps with an agent</CardTitle>
          <CardDescription>Choose your chat, meeting, or document. Suggestions include a source quote and are never saved until you accept them.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-[1fr_2fr_auto] sm:items-end">
          <div className="space-y-2"><Label htmlFor="planner-source-type">Source type</Label><Select value={sourceType} onValueChange={(value) => { setSourceType(value as PlannerSourceType); setSourceId(""); setSuggestions([]); }}><SelectTrigger id="planner-source-type" className="w-full"><SelectValue /></SelectTrigger><SelectContent position="popper" align="start"><SelectItem value="chat">Chat</SelectItem><SelectItem value="meeting">Meeting</SelectItem><SelectItem value="document">Document</SelectItem></SelectContent></Select></div>
          <div className="space-y-2">
            <Label htmlFor="planner-source">Source</Label>
            <Select value={sourceId} onValueChange={setSourceId}>
              <SelectTrigger id="planner-source" className="w-full">
                <SelectValue placeholder={`Choose a ${sourceType}…`} />
              </SelectTrigger>
              <SelectContent position="popper" align="start">
                {availableSources.map((source) => (
                  <SelectItem key={source.id} value={source.id}>{source.title}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {sourceType === "chat" && hasMoreConversations && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void loadOlderConversations()}
                disabled={loading || loadingOlderConversations}
              >
                {loadingOlderConversations && <Loader2 className="animate-spin" />}
                {loadingOlderConversations ? "Loading chats…" : "Load older chats"}
              </Button>
            )}
          </div>
          <Button onClick={() => void runPlanner()} disabled={proposing || !sourceId}>{proposing ? <Loader2 className="animate-spin" /> : <Sparkles />} Suggest next steps</Button>
        </CardContent>
      </Card>

      {suggestions.length > 0 && proposalSource && (
        <section aria-labelledby="suggestion-title" className="space-y-3">
          <div><h2 id="suggestion-title" className="text-xl font-bold">Review suggestions</h2><p className="text-sm text-muted-foreground">From {proposalSource.title}. Edit any field, then accept or ignore each item.</p></div>
          {suggestions.map((suggestion, index) => (
            <Card key={`${proposalSource.id}-${index}`} className="rounded-2xl border-primary/20">
              <CardContent className="space-y-4 py-5">
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-2 sm:col-span-2"><Label htmlFor={`suggestion-title-${index}`}>Suggested task</Label><Input id={`suggestion-title-${index}`} value={suggestion.title} disabled={saving} onChange={(event) => setSuggestions((current) => current.map((value, i) => i === index ? { ...value, title: event.target.value } : value))} /></div>
                  <div className="space-y-2 sm:col-span-2"><Label htmlFor={`suggestion-description-${index}`}>Details</Label><textarea id={`suggestion-description-${index}`} value={suggestion.description ?? ""} disabled={saving} onChange={(event) => setSuggestions((current) => current.map((value, i) => i === index ? { ...value, description: event.target.value || null } : value))} rows={2} className="w-full rounded-md border bg-background px-3 py-2 text-sm" /></div>
                </div>
                <blockquote className="rounded-xl border-l-4 border-primary/50 bg-muted/50 px-4 py-3 text-sm text-muted-foreground">“{suggestion.source_quote}”</blockquote>
                <div className="flex flex-wrap items-end gap-3">
                  <div className="space-y-2"><Label htmlFor={`suggestion-priority-${index}`}>Priority</Label><Select value={suggestion.priority} disabled={saving} onValueChange={(priority) => setSuggestions((current) => current.map((value, i) => i === index ? { ...value, priority: priority as ActionItemRecord["priority"] } : value))}><SelectTrigger id={`suggestion-priority-${index}`}><SelectValue /></SelectTrigger><SelectContent position="popper" align="start"><SelectItem value="low">Low</SelectItem><SelectItem value="normal">Normal</SelectItem><SelectItem value="high">High</SelectItem></SelectContent></Select></div>
                  <div className="space-y-2"><Label htmlFor={`suggestion-date-${index}`}>Due date</Label><Input id={`suggestion-date-${index}`} type="date" value={suggestion.due_date ?? ""} disabled={saving} onChange={(event) => setSuggestions((current) => current.map((value, i) => i === index ? { ...value, due_date: event.target.value || null } : value))} /></div>
                  <Button onClick={() => void acceptSuggestion(suggestion)} disabled={saving || !suggestion.title.trim()}><Check /> Accept</Button>
                  <Button variant="outline" onClick={() => ignoreSuggestion(index)} disabled={saving}>Ignore</Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </section>
      )}

      <section aria-labelledby="planner-list-title" className="space-y-3">
        <div className="flex items-end justify-between"><div><h2 id="planner-list-title" className="text-xl font-bold">Your action items</h2><p className="text-sm text-muted-foreground">{items.length} {items.length === 1 ? "item" : "items"}</p></div></div>
        {loading ? <p className="py-8 text-center text-sm text-muted-foreground">Loading your planner…</p> : items.length === 0 ? (
          <Card className="rounded-2xl"><CardContent className="flex flex-col items-center gap-2 py-10 text-center"><CircleCheck className="size-8 text-primary" /><p className="font-medium">Your planner is ready when you are.</p><p className="text-sm text-muted-foreground">Add a next step above to get started.</p></CardContent></Card>
        ) : items.map((item) => (
          <Card key={item.id} className="rounded-2xl">
            <CardContent className="flex flex-col gap-4 py-4 sm:flex-row sm:items-center">
              <div className="min-w-0 flex-1"><p className={`font-semibold ${item.status === "done" ? "text-muted-foreground line-through" : ""}`}>{item.title}</p>{item.description && <p className="mt-1 whitespace-pre-wrap text-sm text-muted-foreground">{item.description}</p>}{item.source_quote && <blockquote className="mt-2 border-l-2 pl-3 text-xs text-muted-foreground">“{item.source_quote}”</blockquote>}<p className="mt-2 text-xs text-muted-foreground">{item.priority} priority{item.due_date ? ` · due ${item.due_date}` : ""}</p></div>
              <div className="flex flex-wrap items-center gap-2">
                <Select value={item.status} onValueChange={(value) => void changeStatus(item, value as ActionItemRecord["status"])}><SelectTrigger aria-label={`Status for ${item.title}`}><SelectValue /></SelectTrigger><SelectContent position="popper" align="start">{Object.entries(statusLabels).map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}</SelectContent></Select>
                <Button variant="outline" size="icon" aria-label={`Edit ${item.title}`} onClick={() => edit(item)}><Pencil className="size-4" /></Button>
                <Button variant="outline" size="icon" aria-label={`Delete ${item.title}`} onClick={() => void remove(item)}><Trash2 className="size-4" /></Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </section>
    </div>
  );
}
