"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, CircleCheck, ListTodo, Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createActionItem, deleteActionItem, getActionItems, updateActionItem } from "@/lib/api";
import type { ActionItemRecord } from "@/lib/schemas";

const statusLabels: Record<ActionItemRecord["status"], string> = {
  next: "To do",
  in_progress: "In progress",
  done: "Done",
};

export default function ActionItemsPage() {
  const [items, setItems] = useState<ActionItemRecord[]>([]);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<ActionItemRecord["priority"]>("normal");
  const [dueDate, setDueDate] = useState("");
  const [editing, setEditing] = useState<ActionItemRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems((await getActionItems()).items);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load action items.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

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
      await load();
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
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not update this action item.");
    }
  };

  const remove = async (item: ActionItemRecord) => {
    try {
      await deleteActionItem(item.id);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not delete this action item.");
    }
  };

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
            <div className="space-y-2"><Label htmlFor="action-priority">Priority</Label><select id="action-priority" value={priority} onChange={(event) => setPriority(event.target.value as ActionItemRecord["priority"])} className="h-10 w-full rounded-md border bg-background px-3 text-sm"><option value="low">Low</option><option value="normal">Normal</option><option value="high">High</option></select></div>
            <div className="space-y-2"><Label htmlFor="action-due-date">Due date</Label><Input id="action-due-date" type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} /></div>
            {error && <p role="alert" className="text-sm text-destructive sm:col-span-2">{error}</p>}
            <div className="flex gap-2 sm:col-span-2">
              <Button type="submit" disabled={saving || !title.trim()}>{saving ? <Loader2 className="animate-spin" /> : editing ? <Check /> : <Plus />}{editing ? "Save changes" : "Add to planner"}</Button>
              {editing && <Button type="button" variant="outline" onClick={resetForm}>Cancel</Button>}
            </div>
          </form>
        </CardContent>
      </Card>

      <section aria-labelledby="planner-list-title" className="space-y-3">
        <div className="flex items-end justify-between"><div><h2 id="planner-list-title" className="text-xl font-bold">Your action items</h2><p className="text-sm text-muted-foreground">{items.length} {items.length === 1 ? "item" : "items"}</p></div></div>
        {loading ? <p className="py-8 text-center text-sm text-muted-foreground">Loading your planner…</p> : items.length === 0 ? (
          <Card className="rounded-2xl"><CardContent className="flex flex-col items-center gap-2 py-10 text-center"><CircleCheck className="size-8 text-primary" /><p className="font-medium">Your planner is ready when you are.</p><p className="text-sm text-muted-foreground">Add a next step above to get started.</p></CardContent></Card>
        ) : items.map((item) => (
          <Card key={item.id} className="rounded-2xl">
            <CardContent className="flex flex-col gap-4 py-4 sm:flex-row sm:items-center">
              <div className="min-w-0 flex-1"><p className={`font-semibold ${item.status === "done" ? "text-muted-foreground line-through" : ""}`}>{item.title}</p>{item.description && <p className="mt-1 whitespace-pre-wrap text-sm text-muted-foreground">{item.description}</p>}<p className="mt-2 text-xs text-muted-foreground">{item.priority} priority{item.due_date ? ` · due ${item.due_date}` : ""}</p></div>
              <div className="flex flex-wrap items-center gap-2">
                <select aria-label={`Status for ${item.title}`} value={item.status} onChange={(event) => void changeStatus(item, event.target.value as ActionItemRecord["status"])} className="h-10 rounded-md border bg-background px-2 text-sm">{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
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
