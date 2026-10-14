"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ExternalLink, Github, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import * as api from "@/lib/api";
import type { ActionItemSuggestion, GitHubIssueProposal, GitHubProjectOverview, GitHubPullDetail, GitHubRepository } from "@/lib/schemas";

export default function GitHubProjectPage() {
  const [repositories, setRepositories] = useState<GitHubRepository[]>([]);
  const [repositoryId, setRepositoryId] = useState("");
  const [overview, setOverview] = useState<GitHubProjectOverview | null>(null);
  const [pullDetail, setPullDetail] = useState<GitHubPullDetail | null>(null);
  const [proposal, setProposal] = useState<GitHubIssueProposal | null>(null);
  const [issueTitle, setIssueTitle] = useState("");
  const [issueBody, setIssueBody] = useState("");
  const [issueReviewed, setIssueReviewed] = useState(false);
  const [commentIssueNumber, setCommentIssueNumber] = useState<number | null>(null);
  const [commentBody, setCommentBody] = useState("");
  const [commentReviewed, setCommentReviewed] = useState(false);
  const [activeTab, setActiveTab] = useState<"issues" | "pulls">("issues");
  const [loadingRepositories, setLoadingRepositories] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    api.getGitHubRepositories()
      .then((result) => {
        const selected = result.repositories.filter((repository) => repository.selected);
        setRepositories(selected);
        setRepositoryId((current) => current || selected[0]?.repository_id || "");
      })
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : "Could not load selected repositories."))
      .finally(() => setLoadingRepositories(false));
  }, []);

  const loadProject = async () => {
    if (!repositoryId) return;
    setBusy(true);
    setError("");
    setMessage("");
    setProposal(null);
    setPullDetail(null);
    setIssueReviewed(false);
    setCommentIssueNumber(null);
    setCommentReviewed(false);
    try {
      setOverview(await api.getGitHubProjectOverview(repositoryId));
    } catch (cause) {
      setOverview(null);
      setError(cause instanceof Error ? cause.message : "Could not load this GitHub project.");
    } finally {
      setBusy(false);
    }
  };

  const suggestTasks = async (issueNumber: number) => {
    if (!repositoryId) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      setProposal(await api.proposeGitHubIssueActions(repositoryId, issueNumber));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not draft planner suggestions.");
    } finally {
      setBusy(false);
    }
  };

  const inspectPull = async (number: number) => {
    if (!repositoryId) return;
    setBusy(true);
    setError("");
    try {
      setPullDetail(await api.getGitHubPullDetail(repositoryId, number));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load pull request details.");
    } finally {
      setBusy(false);
    }
  };

  const acceptSuggestion = async (suggestion: ActionItemSuggestion) => {
    if (!proposal) return;
    setBusy(true);
    setError("");
    try {
      await api.createActionItem({
        title: suggestion.title,
        ...(suggestion.description ? { description: suggestion.description } : {}),
        priority: suggestion.priority,
        ...(suggestion.due_date ? { due_date: suggestion.due_date } : {}),
        source_type: "github",
        source_id: proposal.source_id,
        source_repository_id: proposal.repository_id,
        source_quote: suggestion.source_quote,
      });
      setProposal((current) => current ? { ...current, suggestions: current.suggestions.filter((item) => item !== suggestion) } : current);
      setMessage("Added to your action planner with its GitHub source quote.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not add this task.");
    } finally {
      setBusy(false);
    }
  };

  const createIssue = async () => {
    if (!repositoryId || !issueReviewed || !issueTitle.trim()) return;
    setBusy(true);
    setError("");
    try {
      const created = await api.createGitHubIssue(repositoryId, { title: issueTitle.trim(), body: issueBody });
      setIssueTitle("");
      setIssueBody("");
      setIssueReviewed(false);
      await loadProject();
      setMessage(`Created issue #${created.number}: ${created.title}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create the GitHub issue.");
    } finally {
      setBusy(false);
    }
  };

  const createComment = async () => {
    if (!repositoryId || commentIssueNumber === null || !commentReviewed || !commentBody.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api.createGitHubIssueComment(repositoryId, commentIssueNumber, commentBody.trim());
      setMessage(`Posted your comment to ${overview?.repository} issue #${commentIssueNumber}.`);
      setCommentIssueNumber(null);
      setCommentBody("");
      setCommentReviewed(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not post the GitHub comment.");
    } finally {
      setBusy(false);
    }
  };

  const currentItems = activeTab === "issues" ? overview?.issues ?? [] : overview?.pull_requests ?? [];

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-6 sm:px-8 sm:py-10">
      <section className="brand-panel rounded-3xl border p-6 sm:p-8">
        <div className="flex items-center gap-4">
          <span className="grid size-12 place-items-center rounded-2xl bg-sky-soft text-sky-ink"><Github aria-hidden="true" /></span>
          <div><h1 className="text-2xl font-bold">GitHub Project Agent</h1><p className="mt-1 text-sm text-muted-foreground">Review selected project activity and turn issue next steps into cited planner tasks.</p></div>
        </div>
      </section>

      <Card className="rounded-2xl">
        <CardHeader><CardTitle>Choose a project</CardTitle><CardDescription>The agent can read only repositories you selected in Settings.</CardDescription></CardHeader>
        <CardContent className="flex flex-col gap-3 sm:flex-row">
          {loadingRepositories ? <p className="text-sm text-muted-foreground">Loading selected repositories…</p> : repositories.length ? <>
            <Select value={repositoryId} disabled={busy} onValueChange={(value) => { setRepositoryId(value); setOverview(null); setProposal(null); setPullDetail(null); setIssueTitle(""); setIssueBody(""); setIssueReviewed(false); setCommentIssueNumber(null); setCommentBody(""); setCommentReviewed(false); }}>
              <SelectTrigger aria-label="Selected repository" className="min-w-0 flex-1"><SelectValue /></SelectTrigger>
              <SelectContent position="popper" align="start">
                {repositories.map((repository) => <SelectItem key={repository.repository_id} value={repository.repository_id}>{repository.full_name}</SelectItem>)}
              </SelectContent>
            </Select>
              <Button onClick={() => void loadProject()} disabled={busy || !repositoryId}>{busy ? <Loader2 className="animate-spin" /> : <RefreshCw />} Load project</Button>
          </> : <p className="text-sm text-muted-foreground">No repositories selected. Connect GitHub and choose repositories in <Link className="underline" href="/settings">Settings</Link>.</p>}
        </CardContent>
      </Card>

      {error && <p role="alert" className="rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">{error}</p>}
      {message && <p role="status" className="rounded-xl border border-primary/30 bg-primary/5 px-4 py-3 text-sm">{message} <Link className="underline" href="/action-items">View planner</Link></p>}

      {overview && <>
        <Card className="rounded-2xl">
          <CardHeader><CardTitle>Create an issue</CardTitle><CardDescription>Review the exact title and body before the agent submits them to {overview.repository}.</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            {!issueReviewed ? <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); setIssueReviewed(true); }}>
              <label className="block space-y-1 text-sm font-medium">Issue title<input required maxLength={256} value={issueTitle} onChange={(event) => setIssueTitle(event.target.value)} className="mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal" /></label>
              <label className="block space-y-1 text-sm font-medium">Issue body<textarea maxLength={10000} rows={4} value={issueBody} onChange={(event) => setIssueBody(event.target.value)} className="mt-1 w-full rounded-md border bg-background px-3 py-2 font-normal" /></label>
              <Button type="submit" disabled={!issueTitle.trim()}>Review issue draft</Button>
            </form> : <div className="space-y-3 rounded-xl border p-4">
              <p className="text-xs font-semibold uppercase text-muted-foreground">Will create in {overview.repository}</p>
              <h3 className="font-semibold">{issueTitle.trim()}</h3>
              <p className="whitespace-pre-wrap break-words text-sm">{issueBody || "(No body)"}</p>
              <div className="flex flex-wrap gap-2"><Button onClick={() => void createIssue()} disabled={busy}>{busy ? <Loader2 className="animate-spin" /> : null}Create issue on GitHub</Button><Button variant="outline" onClick={() => setIssueReviewed(false)} disabled={busy}>Edit draft</Button></div>
            </div>}
          </CardContent>
        </Card>
        <div className="flex gap-2" role="tablist" aria-label="Project activity">
          <Button role="tab" aria-selected={activeTab === "issues"} variant={activeTab === "issues" ? "default" : "outline"} onClick={() => setActiveTab("issues")}>Issues ({overview.issues.length})</Button>
          <Button role="tab" aria-selected={activeTab === "pulls"} variant={activeTab === "pulls" ? "default" : "outline"} onClick={() => setActiveTab("pulls")}>Pull requests ({overview.pull_requests.length})</Button>
        </div>
        <section className="space-y-3" aria-label={activeTab === "issues" ? "Open issues" : "Open pull requests"}>
          {currentItems.length ? currentItems.map((item) => <Card key={item.number} className="rounded-2xl"><CardContent className="space-y-3 py-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0"><h2 className="font-semibold">{item.title} <span className="text-xs font-normal text-muted-foreground">#{item.number}</span></h2><p className="mt-1 text-xs text-muted-foreground">{item.author ? `@${item.author}` : "Unknown author"}{item.updated_at ? ` · updated ${new Date(item.updated_at).toLocaleDateString()}` : ""}{"draft" in item && item.draft ? " · draft" : ""}</p></div>
              <a className="inline-flex items-center gap-1 text-sm underline" href={item.html_url} target="_blank" rel="noreferrer">Open on GitHub <ExternalLink className="size-3" /></a>
            </div>
            {item.body && <p className="whitespace-pre-wrap break-words text-sm text-muted-foreground">{item.body}</p>}
            <div className="flex flex-wrap gap-2">{item.labels.map((label) => <span key={label} className="rounded-full bg-muted px-2 py-1 text-xs">{label}</span>)}</div>
            {activeTab === "issues" ? <div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={() => void suggestTasks(item.number)} disabled={busy}><Sparkles className="size-4" /> Suggest planner tasks</Button><Button variant="outline" size="sm" onClick={() => { setCommentIssueNumber(item.number); setCommentBody(""); setCommentReviewed(false); }}>Write comment</Button></div> : <Button variant="outline" size="sm" onClick={() => void inspectPull(item.number)} disabled={busy}>View diff and checks</Button>}
          </CardContent></Card>) : <Card className="rounded-2xl"><CardContent className="py-8 text-center text-sm text-muted-foreground">No open {activeTab} in this repository.</CardContent></Card>}
        </section>
      </>}

      {commentIssueNumber !== null && overview && <Card className="rounded-2xl border-primary/30"><CardHeader><CardTitle>Comment on issue #{commentIssueNumber}</CardTitle><CardDescription>Review the exact comment and destination before posting to {overview.repository}.</CardDescription></CardHeader><CardContent className="space-y-3">
        {!commentReviewed ? <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); setCommentReviewed(true); }}><label className="block space-y-1 text-sm font-medium">Comment<textarea required maxLength={10000} rows={4} value={commentBody} onChange={(event) => setCommentBody(event.target.value)} className="mt-1 w-full rounded-md border bg-background px-3 py-2 font-normal" /></label><div className="flex gap-2"><Button type="submit" disabled={!commentBody.trim()}>Review comment</Button><Button variant="outline" type="button" onClick={() => setCommentIssueNumber(null)}>Cancel</Button></div></form> : <div className="space-y-3 rounded-xl border p-4"><p className="text-xs font-semibold uppercase text-muted-foreground">Will post to {overview.repository} issue #{commentIssueNumber}</p><p className="whitespace-pre-wrap break-words text-sm">{commentBody.trim()}</p><div className="flex gap-2"><Button onClick={() => void createComment()} disabled={busy}>{busy ? <Loader2 className="animate-spin" /> : null}Post comment to GitHub</Button><Button variant="outline" onClick={() => setCommentReviewed(false)} disabled={busy}>Edit comment</Button></div></div>}
      </CardContent></Card>}

      {proposal && <Card className="rounded-2xl border-primary/30"><CardHeader><CardTitle>Review planner suggestions</CardTitle><CardDescription>From {proposal.source_title}. GitHub text is treated as untrusted source material; nothing is saved until you accept an item.</CardDescription></CardHeader><CardContent className="space-y-4">
        {proposal.suggestions.length ? proposal.suggestions.map((suggestion, index) => <div key={`${proposal.source_id}-${index}`} className="space-y-3 rounded-xl border p-4">
          <p className="font-medium">{suggestion.title}</p>{suggestion.description && <p className="text-sm text-muted-foreground">{suggestion.description}</p>}
          <blockquote className="border-l-2 border-primary/50 pl-3 text-sm text-muted-foreground">“{suggestion.source_quote}”</blockquote>
          <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-xs text-muted-foreground">{suggestion.priority} priority{suggestion.due_date ? ` · due ${suggestion.due_date}` : ""}</span><div className="flex gap-2"><Button onClick={() => void acceptSuggestion(suggestion)} disabled={busy}>Add to planner</Button><Button variant="outline" onClick={() => setProposal((current) => current ? { ...current, suggestions: current.suggestions.filter((item) => item !== suggestion) } : current)}>Ignore</Button></div></div>
        </div>) : <p className="text-sm text-muted-foreground">No clear action items were found in this issue.</p>}
      </CardContent></Card>}

      {pullDetail && <Card className="rounded-2xl"><CardHeader><CardTitle>Pull request #{pullDetail.number}: {pullDetail.title}</CardTitle><CardDescription><a className="underline" href={pullDetail.html_url} target="_blank" rel="noreferrer">Open pull request on GitHub</a></CardDescription></CardHeader><CardContent className="space-y-5">
        <section><h3 className="mb-2 font-semibold">Checks</h3>{pullDetail.checks.length ? <ul className="space-y-2">{pullDetail.checks.map((check, index) => <li key={`${check.name}-${index}`} className="flex flex-wrap justify-between gap-2 rounded-lg border px-3 py-2 text-sm"><span>{check.name}</span><span className="text-muted-foreground">{check.conclusion ?? check.status}</span></li>)}</ul> : <p className="text-sm text-muted-foreground">No check runs found for the latest commit.</p>}{pullDetail.checks_truncated && <p className="mt-2 text-xs text-muted-foreground">Showing the first 50 checks.</p>}</section>
        <section><h3 className="mb-2 font-semibold">Changed files</h3>{pullDetail.files.map((file) => <details key={file.filename} className="mb-2 rounded-lg border"><summary className="cursor-pointer px-3 py-2 text-sm">{file.filename} · +{file.additions} / −{file.deletions}</summary>{file.patch && <pre className="max-h-80 overflow-auto border-t bg-muted/40 p-3 text-xs">{file.patch}</pre>}{!file.patch && <p className="border-t p-3 text-xs text-muted-foreground">GitHub did not include a text patch for this file.</p>}</details>)}{pullDetail.files_truncated && <p className="text-xs text-muted-foreground">Showing the first 20 changed files.</p>}</section>
      </CardContent></Card>}
    </div>
  );
}
