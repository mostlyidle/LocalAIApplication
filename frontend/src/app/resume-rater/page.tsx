"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  BriefcaseBusiness,
  Check,
  ChevronDown,
  CircleHelp,
  FileText,
  Loader2,
  Pencil,
  Plus,
  Printer,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import * as api from "@/lib/api";
import type {
  ResumeRaterCandidate,
  ResumeRaterCriterion,
  ResumeRaterRevision,
  ResumeRaterWorkspace,
  ResumeRaterWorkspaceDetail,
} from "@/lib/schemas";

const MAX_CANDIDATES = 25;
const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;
const BUSY_STATUSES = new Set(["queued", "processing", "rubric_queued", "rubric_processing"]);

const LEVEL_LABELS: Record<string, string> = {
  not_demonstrated: "Not demonstrated",
  weak: "Weak evidence",
  partial: "Partial evidence",
  substantial: "Substantial evidence",
  fully_meets: "Strong evidence",
};

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    rubric_queued: "Preparing rubric",
    rubric_processing: "Preparing rubric",
    needs_review: "Rubric ready for review",
    approved: "Rubric approved",
    queued: "Waiting in queue",
    processing: "Assessing resume",
    completed: "Assessment ready",
    needs_attention: "Needs attention",
    cancelled: "Cancelled",
  };
  return labels[status] ?? status.replaceAll("_", " ");
}

function StatusBadge({ status }: { status: string }) {
  const variant = status === "needs_attention" ? "destructive"
    : status === "approved" || status === "completed" ? "secondary" : "outline";
  return <Badge variant={variant}>{BUSY_STATUSES.has(status) && <Loader2 className="size-3 animate-spin" aria-hidden="true" />}{statusLabel(status)}</Badge>;
}

function ErrorNotice({ children }: { children: string }) {
  return <p role="alert" className="rounded-xl border border-destructive/35 bg-destructive/5 px-4 py-3 text-sm text-destructive">{children}</p>;
}

function PointList({ title, points, criteria }: {
  title: string;
  points: Array<{ criterion_id: string; text: string; evidence_quotes: string[] }>;
  criteria: ResumeRaterCriterion[];
}) {
  if (!points.length) return null;
  return (
    <section aria-label={title}>
      <h4 className="text-sm font-semibold">{title}</h4>
      <ul className="mt-2 space-y-3">
        {points.map((point, index) => (
          <li key={`${point.criterion_id}-${index}`} className="rounded-xl bg-muted/45 p-3 text-sm">
            <p>{point.text}</p>
            <p className="mt-1 text-xs font-medium text-muted-foreground">
              {criteria.find((criterion) => criterion.id === point.criterion_id)?.label ?? "Job criterion"}
            </p>
            {point.evidence_quotes.map((quote) => (
              <blockquote key={quote} className="mt-2 border-l-2 border-primary/40 pl-3 text-xs leading-relaxed text-muted-foreground">“{quote}”</blockquote>
            ))}
          </li>
        ))}
      </ul>
    </section>
  );
}

type ResumeRaterAssessment = ResumeRaterCandidate["history"][number];
type ResumeRaterReport = NonNullable<ResumeRaterAssessment["result"]>;

function AssessmentReportContent({
  report,
  criteria,
  mustHavesNotMet,
  showSummary = true,
}: {
  report: ResumeRaterReport;
  criteria: ResumeRaterCriterion[];
  mustHavesNotMet: string[];
  showSummary?: boolean;
}) {
  return (
    <div className="space-y-5">
      {showSummary && <div>
        <h4 className="text-sm font-semibold">Assessment summary</h4>
        <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{report.summary}</p>
      </div>}

      {mustHavesNotMet.length > 0 && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
          <h4 className="flex items-center gap-2 text-sm font-semibold text-amber-800 dark:text-amber-200">
            <AlertTriangle className="size-4" aria-hidden="true" /> Must-haves below the evidence threshold
          </h4>
          <ul className="mt-2 list-inside list-disc text-sm">
            {mustHavesNotMet.map((id) => (
              <li key={id}>{criteria.find((criterion) => criterion.id === id)?.label ?? id}</li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted-foreground">Review the cited evidence and follow up with the candidate. This flag does not make a hiring decision.</p>
        </div>
      )}

      <div>
        <h4 className="text-sm font-semibold">Job-related criteria</h4>
        <ul className="mt-2 grid gap-3 md:grid-cols-2">
          {report.criterion_scores.map((score) => {
            const criterion = criteria.find((item) => item.id === score.criterion_id);
            return (
              <li key={score.criterion_id} className="rounded-xl border p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-medium">{criterion?.label ?? score.criterion_id}</span>
                  <Badge variant="outline">{LEVEL_LABELS[score.level] ?? score.level}</Badge>
                </div>
                <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{score.explanation}</p>
                {score.evidence_quotes.map((quote) => (
                  <blockquote key={quote} className="mt-2 border-l-2 border-primary/40 pl-3 text-xs leading-relaxed">“{quote}”</blockquote>
                ))}
              </li>
            );
          })}
        </ul>
      </div>

      <PointList title="Strengths" points={report.strengths} criteria={criteria} />
      <PointList title="Gaps to explore" points={report.gaps} criteria={criteria} />

      {report.resume_suggestions.length > 0 && (
        <section aria-label="Resume improvement suggestions">
          <h4 className="text-sm font-semibold">Resume improvement suggestions</h4>
          <ul className="mt-2 space-y-2">
            {report.resume_suggestions.map((suggestion, index) => (
              <li key={`${suggestion.source_quote}-${index}`} className="rounded-xl bg-muted/45 p-3 text-sm">
                <p>{suggestion.text}</p>
                <blockquote className="mt-2 border-l-2 border-primary/40 pl-3 text-xs text-muted-foreground">“{suggestion.source_quote}”</blockquote>
              </li>
            ))}
          </ul>
        </section>
      )}

      {report.interview_questions.length > 0 && (
        <section aria-label="Suggested interview questions">
          <h4 className="text-sm font-semibold">Suggested interview questions</h4>
          <ol className="mt-2 list-inside list-decimal space-y-2 text-sm">
            {report.interview_questions.map((question) => <li key={question}>{question}</li>)}
          </ol>
        </section>
      )}
    </div>
  );
}

function AssessmentDetails({
  assessment,
  candidate,
  criteria,
  revisions,
}: {
  assessment: ResumeRaterCandidate["current_assessment"];
  candidate: ResumeRaterCandidate;
  criteria: ResumeRaterCriterion[];
  revisions: ResumeRaterRevision[];
}) {
  const report = assessment?.result;
  const previousAssessments = candidate.history.filter((item) => item.id !== assessment?.id);
  if (!report && previousAssessments.length === 0) return null;
  return (
    <div className="mt-5 space-y-5 border-t pt-5">
      {report && assessment && (
        <AssessmentReportContent
          report={report}
          criteria={criteria}
          mustHavesNotMet={assessment.must_haves_not_met}
        />
      )}

      {previousAssessments.length > 0 && (
        <details className="rounded-xl border p-3">
          <summary className="flex list-none items-center justify-between gap-3 text-sm font-medium">
            Previous assessments ({previousAssessments.length})
            <ChevronDown className="size-4 text-muted-foreground" aria-hidden="true" />
          </summary>
          <ul className="mt-3 space-y-3">
            {previousAssessments.map((item) => (
              <li key={item.id} className="border-t pt-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span>Revision {item.revision_version}</span>
                  <span>{item.score === null ? statusLabel(item.status) : `${item.score}/100`}</span>
                </div>
                {item.result && <p className="mt-1 text-xs text-muted-foreground">{item.result.summary}</p>}
                {item.result && (
                  <details className="mt-3 rounded-lg bg-muted/35 p-3">
                    <summary className="cursor-pointer text-xs font-medium">View evidence and recommendations</summary>
                    <div className="mt-4">
                      <AssessmentReportContent
                        report={item.result}
                        criteria={revisions.find((revision) => revision.version === item.revision_version)?.criteria ?? []}
                        mustHavesNotMet={item.must_haves_not_met}
                        showSummary={false}
                      />
                    </div>
                  </details>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export default function ResumeRaterPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const selectedIdRef = useRef("");
  const workspaceRequestRef = useRef(0);
  const [workspaces, setWorkspaces] = useState<ResumeRaterWorkspace[]>([]);
  const [workspace, setWorkspace] = useState<ResumeRaterWorkspaceDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busyAction, setBusyAction] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [showCreate, setShowCreate] = useState(true);
  const [jobTitle, setJobTitle] = useState("");
  const [jobPosting, setJobPosting] = useState("");
  const [editedPosting, setEditedPosting] = useState("");
  const [editingPosting, setEditingPosting] = useState(false);
  const [rubricDraft, setRubricDraft] = useState<ResumeRaterCriterion[] | null>(null);
  const [editingApprovedRubric, setEditingApprovedRubric] = useState(false);
  const [nameDrafts, setNameDrafts] = useState<Record<string, string>>({});
  const [activeCandidate, setActiveCandidate] = useState("");

  const refreshWorkspace = useCallback(async (workspaceId: string) => {
    const shouldApply = selectedIdRef.current === workspaceId;
    const requestId = shouldApply ? ++workspaceRequestRef.current : null;
    const detail = await api.getResumeRaterWorkspace(workspaceId);
    if (requestId !== null
      && requestId === workspaceRequestRef.current
      && selectedIdRef.current === workspaceId) {
      setWorkspace(detail);
      setSelectedId(detail.id);
      setWorkspaces((current) => current.map((item) => item.id === detail.id
        ? { ...item, candidate_count: detail.candidate_count, current_revision: detail.current_revision, revision_status: detail.revision_status }
        : item));
      const currentRevision = detail.revisions.find((revision) => revision.version === detail.current_revision);
      setRubricDraft(currentRevision?.criteria?.map((criterion) => ({ ...criterion })) ?? null);
    }
    return detail;
  }, []);

  const loadWorkspaces = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const items = await api.getResumeRaterWorkspaces();
      setWorkspaces(items);
      const activeId = selectedIdRef.current;
      if (activeId && items.some((item) => item.id === activeId)) {
        await refreshWorkspace(activeId);
      } else if (items.length > 0) {
        selectedIdRef.current = items[0].id;
        await refreshWorkspace(items[0].id);
        setShowCreate(false);
      } else {
        workspaceRequestRef.current += 1;
        setWorkspace(null);
        setSelectedId("");
        selectedIdRef.current = "";
        setShowCreate(true);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load hiring workspaces.");
    } finally {
      setLoading(false);
    }
  }, [refreshWorkspace]);

  useEffect(() => { void loadWorkspaces(); }, [loadWorkspaces]);

  const hasPendingWork = workspace !== null && (
    BUSY_STATUSES.has(workspace.revision_status)
    || workspace.candidates.some((candidate) => candidate.current_assessment
      && BUSY_STATUSES.has(candidate.current_assessment.status))
  );
  const pendingWorkspaceId = hasPendingWork ? workspace?.id ?? null : null;

  useEffect(() => {
    if (!pendingWorkspaceId) return;
    let polling = false;
    const timer = window.setInterval(() => {
      if (polling) return;
      polling = true;
      void refreshWorkspace(pendingWorkspaceId).catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : "Could not refresh assessment status.");
      }).finally(() => { polling = false; });
    }, 2000);
    return () => window.clearInterval(timer);
  }, [pendingWorkspaceId, refreshWorkspace]);

  const currentRevision = workspace?.revisions.find((revision) => revision.version === workspace.current_revision) ?? null;
  const criteria = currentRevision?.criteria ?? [];
  const rubricHasChanges = rubricDraft !== null && JSON.stringify(rubricDraft) !== JSON.stringify(criteria);
  const showRubricEditor = workspace !== null && rubricDraft !== null && (
    workspace.revision_status === "needs_review"
    || (workspace.revision_status === "approved" && editingApprovedRubric)
  );
  const completedCount = workspace?.candidates.filter((candidate) => candidate.current_assessment?.status === "completed").length ?? 0;
  const sortedCandidates = useMemo(() => [...(workspace?.candidates ?? [])].sort((left, right) => {
    const leftRank = left.current_assessment?.rank;
    const rightRank = right.current_assessment?.rank;
    if (leftRank !== null && leftRank !== undefined && rightRank !== null && rightRank !== undefined) {
      return leftRank - rightRank || left.display_name.localeCompare(right.display_name);
    }
    if (leftRank !== null && leftRank !== undefined) return -1;
    if (rightRank !== null && rightRank !== undefined) return 1;
    return left.display_name.localeCompare(right.display_name);
  }), [workspace?.candidates]);

  const runAction = async (label: string, action: () => Promise<void>) => {
    setBusyAction(label);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The request could not be completed.");
    } finally {
      setBusyAction("");
    }
  };

  const createWorkspace = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!jobTitle.trim() || jobPosting.trim().length < 100) return;
    await runAction("create", async () => {
      const created = await api.createResumeRaterWorkspace({
        title: jobTitle.trim(),
        job_posting: jobPosting.trim(),
      });
      setWorkspace(created);
      setSelectedId(created.id);
      selectedIdRef.current = created.id;
      setWorkspaces((current) => [
        { ...created, candidate_count: created.candidate_count },
        ...current.filter((item) => item.id !== created.id),
      ]);
      setRubricDraft(null);
      setEditingApprovedRubric(false);
      setJobTitle("");
      setJobPosting("");
      setShowCreate(false);
      setNotice("Job saved. The local model is preparing criteria for your review.");
    });
  };

  const startNewWorkspace = () => {
    setError("");
    setNotice("");
    workspaceRequestRef.current += 1;
    setWorkspace(null);
    setSelectedId("");
    selectedIdRef.current = "";
    setRubricDraft(null);
    setEditingApprovedRubric(false);
    setShowCreate(true);
  };

  const selectWorkspace = (item: ResumeRaterWorkspace) => {
    setError("");
    setNotice("");
    setShowCreate(false);
    selectedIdRef.current = item.id;
    setSelectedId(item.id);
    void runAction("load", async () => { await refreshWorkspace(item.id); });
  };

  const updateCriterion = (criterionId: string, patch: Partial<ResumeRaterCriterion>) => {
    setRubricDraft((current) => current?.map((item) => item.id === criterionId ? { ...item, ...patch } : item) ?? null);
  };

  const addCriterion = () => {
    setRubricDraft((current) => {
      if (!current || current.length >= 8) return current;
      const largest = current.reduce((bestIndex, item, index) => item.weight > current[bestIndex].weight ? index : bestIndex, 0);
      const next = current.map((item, index) => index === largest ? { ...item, weight: item.weight - 10 } : item);
      let id = `manager_added_${Date.now()}`;
      while (next.some((item) => item.id === id)) id += "_1";
      return [...next, {
        id,
        label: "New job-related criterion",
        description: "Describe the qualification and how it can be assessed.",
        weight: 10,
        must_have: false,
      }];
    });
  };

  const removeCriterion = (criterionId: string) => {
    setRubricDraft((current) => {
      if (!current || current.length <= 3) return current;
      const removed = current.find((item) => item.id === criterionId);
      if (!removed) return current;
      const remaining = current.filter((item) => item.id !== criterionId);
      const largestIndex = remaining.reduce((bestIndex, item, index) => item.weight > remaining[bestIndex].weight ? index : bestIndex, 0);
      return remaining.map((item, index) => index === largestIndex ? { ...item, weight: item.weight + removed.weight } : item);
    });
  };

  const rubricTotal = rubricDraft?.reduce((total, criterion) => total + (Number.isFinite(criterion.weight) ? criterion.weight : 0), 0) ?? 0;

  const saveRubric = async () => {
    if (!workspace || !rubricDraft || rubricTotal !== 100 || rubricDraft.length < 3 || rubricDraft.length > 8) return;
    await runAction("rubric", async () => {
      await api.updateResumeRaterRubric(workspace.id, workspace.current_revision, rubricDraft);
      await refreshWorkspace(workspace.id);
      setNotice("Rubric saved as a new revision. Review it, then approve it to score candidates.");
    });
  };

  const approveRubric = async () => {
    if (!workspace) return;
    await runAction("approve", async () => {
      await api.approveResumeRaterRubric(workspace.id, workspace.current_revision);
      const detail = await refreshWorkspace(workspace.id);
      setEditingApprovedRubric(false);
      setNotice(detail.candidate_count > 0
        ? `Rubric approved. ${detail.candidate_count} candidate${detail.candidate_count === 1 ? "" : "s"} queued for assessment.`
        : "Rubric approved. You can now add resumes to this job.");
    });
  };

  const savePostingRevision = async () => {
    if (!workspace || editedPosting.trim().length < 100) return;
    await runAction("posting", async () => {
      await api.createResumeRaterRevision(workspace.id, editedPosting.trim());
      await refreshWorkspace(workspace.id);
      setEditingPosting(false);
      setNotice("Job posting saved as a new revision. Its criteria need review before candidates are rerated.");
    });
  };

  const uploadCandidates = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (!workspace || files.length === 0) return;
    const remaining = MAX_CANDIDATES - workspace.candidate_count;
    if (files.length > remaining) {
      setError(`This job has room for ${remaining} more candidate${remaining === 1 ? "" : "s"}.`);
      return;
    }
    const totalBytes = files.reduce((total, file) => total + file.size, 0);
    if (totalBytes > MAX_UPLOAD_BYTES) {
      setError("The combined size of the selected resumes must be 50 MB or less.");
      return;
    }
    if (files.some((file) => !/\.(pdf|docx)$/i.test(file.name))) {
      setError("Upload PDF or DOCX resumes only.");
      return;
    }
    await runAction("upload", async () => {
      const detail = await api.uploadResumeRaterCandidates(workspace.id, files);
      setWorkspace(detail);
      setWorkspaces((current) => current.map((item) => item.id === detail.id
        ? { ...item, candidate_count: detail.candidate_count, current_revision: detail.current_revision, revision_status: detail.revision_status }
        : item));
      setNotice(`${files.length} resume${files.length === 1 ? "" : "s"} added to this job.`);
    });
  };

  const renameCandidate = async (candidate: ResumeRaterCandidate) => {
    if (!workspace) return;
    const displayName = (nameDrafts[candidate.id] ?? candidate.display_name).trim();
    if (!displayName || displayName === candidate.display_name) return;
    await runAction(`rename-${candidate.id}`, async () => {
      await api.renameResumeRaterCandidate(workspace.id, candidate.id, displayName);
      await refreshWorkspace(workspace.id);
      setNameDrafts((current) => { const next = { ...current }; delete next[candidate.id]; return next; });
      setNotice("Candidate name updated.");
    });
  };

  const retryCandidate = async (candidate: ResumeRaterCandidate) => {
    if (!workspace) return;
    await runAction(`retry-${candidate.id}`, async () => {
      await api.retryResumeRaterCandidate(workspace.id, candidate.id);
      await refreshWorkspace(workspace.id);
      setNotice(`Assessment queued for ${candidate.display_name}.`);
    });
  };

  const cancelCandidate = async (candidate: ResumeRaterCandidate) => {
    if (!workspace) return;
    await runAction(`cancel-${candidate.id}`, async () => {
      await api.cancelResumeRaterCandidate(workspace.id, candidate.id);
      await refreshWorkspace(workspace.id);
      setNotice(`Assessment cancelled for ${candidate.display_name}.`);
    });
  };

  const retryRubric = async () => {
    if (!workspace) return;
    await runAction("retry-rubric", async () => {
      await api.retryResumeRaterRubric(workspace.id, workspace.current_revision);
      await refreshWorkspace(workspace.id);
      setNotice("Rubric drafting queued again.");
    });
  };

  const cancelRubric = async () => {
    if (!workspace) return;
    await runAction("cancel-rubric", async () => {
      await api.cancelResumeRaterRubric(workspace.id, workspace.current_revision);
      await refreshWorkspace(workspace.id);
      setNotice("Rubric drafting cancelled.");
    });
  };

  const deleteCandidate = async (candidate: ResumeRaterCandidate) => {
    if (!workspace || !window.confirm(`Delete ${candidate.display_name}, the uploaded resume, and all saved reports?`)) return;
    await runAction(`delete-${candidate.id}`, async () => {
      await api.deleteResumeRaterCandidate(workspace.id, candidate.id);
      await refreshWorkspace(workspace.id);
      setNotice("Candidate resume and assessment history deleted.");
    });
  };

  const deleteWorkspace = async () => {
    if (!workspace || !window.confirm(`Delete “${workspace.title}”, all candidate resumes, and all assessment history?`)) return;
    await runAction("delete-workspace", async () => {
      await api.deleteResumeRaterWorkspace(workspace.id);
      workspaceRequestRef.current += 1;
      setWorkspace(null);
      setSelectedId("");
      selectedIdRef.current = "";
      setRubricDraft(null);
      setWorkspaces((current) => current.filter((item) => item.id !== workspace.id));
      setShowCreate(true);
      setNotice("Job workspace and its candidate data deleted.");
    });
  };

  const revisions = [...(workspace?.revisions ?? [])].sort((a, b) => b.version - a.version);

  return (
    <div className="resume-rater-page mx-auto w-full max-w-7xl space-y-6 px-4 py-6 sm:px-8 sm:py-9">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-violet-soft text-violet-ink">
            <BriefcaseBusiness className="size-6" aria-hidden="true" />
          </span>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-violet-ink">Hiring workspace</p>
            <h1 className="mt-1 text-2xl font-semibold sm:text-3xl">Resume Rater</h1>
            <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted-foreground">
              Compare candidate evidence against a reviewed job rubric, then explore the reports together.
            </p>
          </div>
        </div>
        <div className="resume-rater-no-print flex flex-wrap gap-2">
          {workspace && <Button variant="outline" onClick={() => window.print()}><Printer className="size-4" aria-hidden="true" />Print reports</Button>}
          {!showCreate && <Button onClick={startNewWorkspace}><Plus className="size-4" aria-hidden="true" />New job</Button>}
        </div>
      </header>

      <div className="resume-rater-no-print grid gap-3 rounded-2xl border border-mint-ink/15 bg-mint-soft/60 p-4 sm:grid-cols-2">
        <p className="flex items-start gap-2 text-sm"><ShieldCheck className="mt-0.5 size-4 shrink-0 text-mint-ink" aria-hidden="true" /><span>The app tries to strip obvious names and contact details before model review. Some identifying details may remain.</span></p>
        <p className="flex items-start gap-2 text-sm"><CircleHelp className="mt-0.5 size-4 shrink-0 text-mint-ink" aria-hidden="true" /><span>Ratings organize job-related evidence for review. A manager makes every hiring decision; scores never reject candidates automatically.</span></p>
      </div>

      {error && <ErrorNotice>{error}</ErrorNotice>}
      {notice && <p role="status" className="rounded-xl border bg-card px-4 py-3 text-sm">{notice}</p>}

      {loading ? (
        <div role="status" className="flex items-center gap-2 rounded-2xl border bg-card p-6 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" aria-hidden="true" />Loading hiring workspaces…</div>
      ) : (
        <div className={`grid items-start gap-6 ${workspaces.length > 0 ? "lg:grid-cols-[260px_minmax(0,1fr)]" : ""}`}>
          {workspaces.length > 0 && (
            <aside className="resume-rater-no-print rounded-2xl border bg-card p-3" aria-label="Job workspaces">
              <div className="flex items-center justify-between px-2 pb-2 pt-1">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Open jobs</h2>
                <Button variant="ghost" size="icon" aria-label="Refresh hiring workspaces" onClick={() => void loadWorkspaces()}><RefreshCw className="size-4" aria-hidden="true" /></Button>
              </div>
              <nav className="space-y-1" aria-label="Select job workspace">
                {workspaces.map((item) => {
                  const active = selectedId === item.id;
                  return (
                    <button key={item.id} type="button" onClick={() => selectWorkspace(item)} className={`w-full rounded-xl p-3 text-left transition-colors ${active ? "bg-violet-soft text-violet-ink" : "hover:bg-muted/70"}`} aria-current={active ? "page" : undefined}>
                      <span className="block truncate text-sm font-semibold">{item.title}</span>
                      <span className="mt-1 flex items-center justify-between gap-2 text-xs text-muted-foreground"><span>{item.candidate_count} / {MAX_CANDIDATES} candidates</span><StatusBadge status={item.revision_status} /></span>
                    </button>
                  );
                })}
              </nav>
            </aside>
          )}

          <div className="min-w-0 space-y-5">
            {showCreate || !workspace ? (
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-lg"><Sparkles className="size-5 text-violet-ink" aria-hidden="true" />Start a job workspace</CardTitle>
                  <CardDescription>Paste the job posting. A local model will suggest job-related criteria for your review before candidate resumes are assessed.</CardDescription>
                </CardHeader>
                <CardContent>
                  <form className="space-y-4" onSubmit={(event) => void createWorkspace(event)}>
                    <div className="space-y-2">
                      <Label htmlFor="resume-job-title">Job title</Label>
                      <Input id="resume-job-title" value={jobTitle} onChange={(event) => setJobTitle(event.target.value)} maxLength={255} placeholder="Senior backend engineer" required />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="resume-job-posting">Job posting</Label>
                      <Textarea id="resume-job-posting" value={jobPosting} onChange={(event) => setJobPosting(event.target.value)} minLength={100} maxLength={32000} rows={24} placeholder="Paste the complete job description, including required qualifications and responsibilities…" required />
                      <p className="text-xs text-muted-foreground">{jobPosting.length.toLocaleString()} / 32,000 characters · At least 100 characters</p>
                    </div>
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <p className="text-xs text-muted-foreground">The model uses the configured local Ollama resume rating model.</p>
                      <Button type="submit" disabled={busyAction !== "" || !jobTitle.trim() || jobPosting.trim().length < 100}>
                        {busyAction === "create" ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : <ArrowUpRight className="size-4" aria-hidden="true" />}
                        Prepare job rubric
                      </Button>
                    </div>
                  </form>
                </CardContent>
              </Card>
            ) : (
              <>
                <Card>
                  <CardHeader className="gap-4 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <CardTitle className="text-xl">{workspace.title}</CardTitle>
                        <StatusBadge status={workspace.revision_status} />
                        <Badge variant="outline">Revision {workspace.current_revision}</Badge>
                      </div>
                      <CardDescription className="mt-2">{workspace.candidate_count} of {MAX_CANDIDATES} candidate resumes</CardDescription>
                    </div>
                    <div className="resume-rater-no-print flex flex-wrap gap-2">
                      <Button variant="outline" onClick={() => { setEditedPosting(currentRevision?.job_posting ?? ""); setEditingPosting((value) => !value); }}><Pencil className="size-4" aria-hidden="true" />{editingPosting ? "Close editor" : "Edit job posting"}</Button>
                      <Button variant="ghost" onClick={() => void deleteWorkspace()} disabled={busyAction !== ""}><Trash2 className="size-4" aria-hidden="true" />Delete job</Button>
                    </div>
                  </CardHeader>
                  {editingPosting && (
                    <CardContent className="resume-rater-no-print border-t pt-5">
                      <Label htmlFor="resume-posting-edit">New job posting revision</Label>
                      <Textarea id="resume-posting-edit" className="mt-2" value={editedPosting} onChange={(event) => setEditedPosting(event.target.value)} minLength={100} maxLength={32000} rows={8} />
                      <p className="mt-1 text-xs text-muted-foreground">A posting change creates a new revision. All candidates must be rerated after its rubric is reviewed and approved.</p>
                      <div className="mt-3 flex justify-end gap-2">
                        <Button variant="outline" onClick={() => setEditingPosting(false)}>Cancel</Button>
                        <Button onClick={() => void savePostingRevision()} disabled={busyAction !== "" || editedPosting.trim().length < 100}>Save new revision</Button>
                      </div>
                    </CardContent>
                  )}
                  <CardContent className="border-t pt-5">
                    <h3 className="text-sm font-semibold">Job posting · revision {currentRevision?.version ?? workspace.current_revision}</h3>
                    <p className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">{currentRevision?.job_posting}</p>
                    {revisions.length > 1 && (
                      <details className="resume-rater-no-print mt-4 rounded-xl border p-3">
                        <summary className="text-sm font-medium">Previous job and rubric revisions</summary>
                        <ul className="mt-3 space-y-3">
                          {revisions.filter((item) => item.version !== workspace.current_revision).map((revision) => (
                            <li key={revision.id} className="border-t pt-3">
                              <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-sm font-medium">Revision {revision.version}</span><StatusBadge status={revision.status} /></div>
                              <p className="mt-1 line-clamp-3 whitespace-pre-wrap text-xs text-muted-foreground">{revision.job_posting}</p>
                              {revision.criteria && (
                                <ul className="mt-3 space-y-2 rounded-lg bg-muted/35 p-3">
                                  {revision.criteria.map((criterion) => (
                                    <li key={criterion.id} className="text-xs">
                                      <p className="font-medium">{criterion.label} · {criterion.weight}%{criterion.must_have ? " · Must-have" : ""}</p>
                                      <p className="mt-0.5 text-muted-foreground">{criterion.description}</p>
                                    </li>
                                  ))}
                                </ul>
                              )}
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </CardContent>
                </Card>

                {(workspace.revision_status === "rubric_queued" || workspace.revision_status === "rubric_processing") && (
                  <Card>
                    <CardContent className="flex flex-wrap items-start justify-between gap-3 py-5">
                      <div className="flex items-start gap-3"><Loader2 className="mt-0.5 size-5 animate-spin text-violet-ink" aria-hidden="true" />
                        <div><h3 className="font-semibold">Preparing a suggested rubric</h3><p className="mt-1 text-sm text-muted-foreground">Your resumes won’t be assessed until you review and approve the criteria.</p></div>
                      </div>
                      <Button variant="outline" onClick={() => void cancelRubric()} disabled={busyAction !== ""}><X className="size-4" aria-hidden="true" />Cancel drafting</Button>
                    </CardContent>
                  </Card>
                )}

                {(workspace.revision_status === "needs_attention" || workspace.revision_status === "cancelled") && (
                  <Card>
                    <CardContent className="flex flex-wrap items-center justify-between gap-3 py-5">
                      <div>
                        {workspace.revision_status === "needs_attention"
                          ? <ErrorNotice>{currentRevision?.error_message ?? "The rubric could not be prepared. Retry after checking the configured local model."}</ErrorNotice>
                          : <p className="text-sm text-muted-foreground">Rubric drafting was cancelled. You can retry this revision.</p>}
                      </div>
                      <Button variant="outline" onClick={() => void retryRubric()} disabled={busyAction !== ""}><RefreshCw className="size-4" aria-hidden="true" />Retry rubric</Button>
                    </CardContent>
                  </Card>
                )}

                {workspace.revision_status === "approved" && (
                  <Card>
                    <CardHeader className="sm:flex-row sm:items-center sm:justify-between">
                      <div><CardTitle className="text-base">Approved scoring rubric</CardTitle><CardDescription className="mt-1">Weights total 100%. Editing creates a new revision and requires rerating all candidates.</CardDescription></div>
                      {!editingApprovedRubric && <Button variant="outline" onClick={() => { setRubricDraft(criteria.map((criterion) => ({ ...criterion }))); setEditingApprovedRubric(true); }}><Pencil className="size-4" aria-hidden="true" />Edit rubric</Button>}
                    </CardHeader>
                    {!editingApprovedRubric && <CardContent className="-mt-3"><ul className="grid gap-2 sm:grid-cols-2">{criteria.map((criterion) => <li key={criterion.id} className="flex items-center justify-between gap-3 rounded-lg bg-muted/40 px-3 py-2 text-sm"><span className="min-w-0 truncate">{criterion.label}{criterion.must_have && <span className="ml-2 text-xs text-amber-700 dark:text-amber-200">Must-have</span>}</span><span className="shrink-0 font-medium">{criterion.weight}%</span></li>)}</ul></CardContent>}
                  </Card>
                )}

                {showRubricEditor && rubricDraft && (
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-lg">{workspace.revision_status === "needs_review" ? "Review the job rubric" : "Edit rubric for a new revision"}</CardTitle>
                      <CardDescription>Adjust the criteria and weights. Must-haves below “substantial evidence” are flagged for follow-up, never used to auto-reject.</CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      {rubricDraft.map((criterion, index) => (
                        <section key={criterion.id} className="rounded-2xl border p-4">
                          <div className="mb-3 flex items-center justify-between gap-3">
                            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Criterion {index + 1}</p>
                            {rubricDraft.length > 3 && <Button variant="ghost" size="icon" aria-label={`Remove ${criterion.label}`} onClick={() => removeCriterion(criterion.id)}><X className="size-4" aria-hidden="true" /></Button>}
                          </div>
                          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_100px]">
                            <div className="space-y-2">
                              <Label htmlFor={`criterion-label-${criterion.id}`}>Criterion name</Label>
                              <Input id={`criterion-label-${criterion.id}`} value={criterion.label} onChange={(event) => updateCriterion(criterion.id, { label: event.target.value })} maxLength={120} />
                            </div>
                            <div className="space-y-2">
                              <Label htmlFor={`criterion-weight-${criterion.id}`}>Weight (%)</Label>
                              <Input id={`criterion-weight-${criterion.id}`} type="number" min={1} max={100} value={criterion.weight} onChange={(event) => updateCriterion(criterion.id, { weight: Number(event.target.value) })} />
                            </div>
                          </div>
                          <div className="mt-3 space-y-2">
                            <Label htmlFor={`criterion-description-${criterion.id}`}>What counts as evidence?</Label>
                            <Textarea id={`criterion-description-${criterion.id}`} value={criterion.description} onChange={(event) => updateCriterion(criterion.id, { description: event.target.value })} maxLength={500} rows={2} />
                          </div>
                          <label className="mt-3 flex items-start gap-2 text-sm">
                            <input type="checkbox" className="mt-1 size-4 accent-primary" checked={criterion.must_have} onChange={(event) => updateCriterion(criterion.id, { must_have: event.target.checked })} />
                            <span><span className="block font-medium">Must-have qualification</span><span className="text-xs text-muted-foreground">Only mark this if the posting explicitly requires it.</span></span>
                          </label>
                        </section>
                      ))}
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <Button variant="outline" onClick={addCriterion} disabled={rubricDraft.length >= 8}><Plus className="size-4" aria-hidden="true" />Add criterion</Button>
                          <span className={`text-sm font-semibold ${rubricTotal === 100 ? "text-mint-ink" : "text-destructive"}`}>Total weight: {rubricTotal}%</span>
                        </div>
                          {editingApprovedRubric && <Button variant="ghost" onClick={() => { setRubricDraft(criteria.map((criterion) => ({ ...criterion }))); setEditingApprovedRubric(false); }}>Cancel edit</Button>}
                          {rubricHasChanges && <Button variant="outline" onClick={() => void saveRubric()} disabled={busyAction !== "" || rubricTotal !== 100 || rubricDraft.some((item) => item.label.trim().length < 2 || item.description.trim().length < 4 || item.weight < 1)}>
                            {busyAction === "rubric" ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : <Check className="size-4" aria-hidden="true" />}Save as new revision
                          </Button>}
                      </div>
                      {workspace.revision_status === "needs_review" && <div className="flex justify-end border-t pt-4">
                        <Button onClick={() => void approveRubric()} disabled={busyAction !== "" || rubricHasChanges || rubricTotal !== 100 || rubricDraft.some((item) => item.label.trim().length < 2 || item.description.trim().length < 4 || item.weight < 1)}>
                          {busyAction === "approve" ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : <Check className="size-4" aria-hidden="true" />}{rubricHasChanges ? "Save rubric edits before approval" : `Approve rubric${workspace.candidate_count > 0 ? " and rerate candidates" : ""}`}
                        </Button>
                      </div>}
                    </CardContent>
                  </Card>
                )}

                {workspace.revision_status === "approved" && (
                  <Card className="resume-rater-no-print border-mint-ink/20">
                    <CardHeader className="sm:flex-row sm:items-center sm:justify-between">
                      <div><CardTitle className="text-base">Add candidate resumes</CardTitle><CardDescription className="mt-1">PDF or DOCX · up to {Math.max(0, MAX_CANDIDATES - workspace.candidate_count)} more · 50 MB combined per upload</CardDescription></div>
                      <Button onClick={() => fileInputRef.current?.click()} disabled={busyAction !== "" || workspace.candidate_count >= MAX_CANDIDATES}>
                        {busyAction === "upload" ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : <Upload className="size-4" aria-hidden="true" />}Choose resumes
                      </Button>
                      <input ref={fileInputRef} type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" multiple className="sr-only" aria-label="Choose PDF or DOCX candidate resumes" onChange={(event) => void uploadCandidates(event)} />
                    </CardHeader>
                    <CardContent className="-mt-3"><p className="flex items-center gap-2 text-xs text-muted-foreground"><ShieldCheck className="size-3.5" aria-hidden="true" />Uploaded files are private to this account and deleted with the candidate or job.</p></CardContent>
                  </Card>
                )}

                {workspace.candidate_count > 0 && (
                  <section aria-labelledby="candidate-heading" className="space-y-4">
                    <div className="flex flex-wrap items-end justify-between gap-2">
                      <div><h2 id="candidate-heading" className="text-lg font-semibold">Candidate comparison</h2><p className="mt-1 text-sm text-muted-foreground">Ranked by score for this approved job revision; equal scores share a rank.</p></div>
                      <Badge variant="outline">{completedCount} / {workspace.candidate_count} rated</Badge>
                    </div>
                    {completedCount < workspace.candidate_count && workspace.revision_status === "approved" && (
                      <p role="status" className="rounded-xl border border-sky-ink/20 bg-sky-soft/50 px-4 py-3 text-sm">The ranking is provisional while assessments are still running or need attention.</p>
                    )}
                    {sortedCandidates.map((candidate) => {
                      const assessment = candidate.current_assessment;
                      const editingName = nameDrafts[candidate.id] !== undefined;
                      const displayName = nameDrafts[candidate.id] ?? candidate.display_name;
                      return (
                        <Card key={candidate.id} className="break-inside-avoid overflow-hidden">
                          <CardHeader className="gap-4 sm:flex-row sm:items-start sm:justify-between">
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-2">
                                {editingName ? (
                                  <Input aria-label="Candidate display name" value={displayName} onChange={(event) => setNameDrafts((current) => ({ ...current, [candidate.id]: event.target.value }))} className="h-9 max-w-xs font-semibold" maxLength={255} />
                                ) : <CardTitle className="text-base">{candidate.display_name}</CardTitle>}
                                {assessment?.score !== null && assessment?.score !== undefined && <Badge variant="secondary">{assessment.score}/100</Badge>}
                                {assessment?.rank !== null && assessment?.rank !== undefined && <Badge variant="outline">Rank #{assessment.rank}</Badge>}
                                {assessment && <StatusBadge status={assessment.status} />}
                              </div>
                              <CardDescription className="mt-1 flex items-center gap-1.5"><FileText className="size-3.5" aria-hidden="true" />{candidate.filename}</CardDescription>
                              {assessment?.status === "needs_attention" && assessment.error_message && <p className="mt-2 text-sm text-destructive">{assessment.error_message}</p>}
                              {assessment && BUSY_STATUSES.has(assessment.status) && <p className="mt-2 text-sm text-muted-foreground">This runs locally and can take a little while.</p>}
                              {!assessment && <p className="mt-2 text-sm text-muted-foreground">Awaiting approval of the current rubric.</p>}
                            </div>
                            <div className="resume-rater-no-print flex flex-wrap gap-1">
                              {editingName ? (
                                <>
                                  <Button variant="outline" size="sm" onClick={() => void renameCandidate(candidate)} disabled={busyAction !== "" || !displayName.trim()}><Check className="size-4" aria-hidden="true" />Save name</Button>
                                  <Button variant="ghost" size="icon" aria-label="Cancel candidate name edit" onClick={() => setNameDrafts((current) => { const next = { ...current }; delete next[candidate.id]; return next; })}><X className="size-4" aria-hidden="true" /></Button>
                                </>
                              ) : <Button variant="ghost" size="icon" aria-label={`Edit ${candidate.display_name} name`} onClick={() => setNameDrafts((current) => ({ ...current, [candidate.id]: candidate.display_name }))}><Pencil className="size-4" aria-hidden="true" /></Button>}
                              {assessment?.status === "needs_attention" && <Button variant="outline" size="sm" onClick={() => void retryCandidate(candidate)} disabled={busyAction !== ""}><RefreshCw className={`size-4 ${busyAction === `retry-${candidate.id}` ? "animate-spin" : ""}`} aria-hidden="true" />Retry</Button>}
                              {assessment && BUSY_STATUSES.has(assessment.status) && <Button variant="outline" size="sm" onClick={() => void cancelCandidate(candidate)} disabled={busyAction !== ""}><X className="size-4" aria-hidden="true" />Cancel</Button>}
                              <Button variant="ghost" size="icon" aria-label={`Delete ${candidate.display_name}`} onClick={() => void deleteCandidate(candidate)} disabled={busyAction !== ""}><Trash2 className="size-4" aria-hidden="true" /></Button>
                            </div>
                          </CardHeader>
                          {(assessment?.result || candidate.history.some((item) => item.id !== assessment?.id)) && (
                            <CardContent className="-mt-3">
                              <details open={activeCandidate === candidate.id} onToggle={(event) => setActiveCandidate(event.currentTarget.open ? candidate.id : "")}>
                                <summary className="flex list-none items-center justify-between gap-3 rounded-xl bg-muted/40 px-3 py-2 text-sm font-medium">
                                  View evidence and assessment history <ChevronDown className="size-4" aria-hidden="true" />
                                </summary>
                                <AssessmentDetails assessment={assessment} candidate={candidate} criteria={criteria} revisions={revisions} />
                              </details>
                            </CardContent>
                          )}
                        </Card>
                      );
                    })}
                  </section>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
