"use client";

import { useEffect, useMemo, useState, type PointerEvent } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Download,
  FileLock2,
  LoaderCircle,
  Plus,
  ShieldCheck,
  Square,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import * as api from "@/lib/api";
import { MAX_FILE_SIZE } from "@/lib/constants";

const SUPPORTED_FORMATS = ["pdf", "png", "jpg", "jpeg", "tiff", "bmp", "webp"];

const CATEGORY_OPTIONS = [
  "person name",
  "employee number",
  "email address",
  "phone number",
  "street address",
  "salary",
  "government identification number",
  "social security number",
  "social insurance number",
  "passport number",
  "driver license number",
  "date of birth",
  "bank account number",
  "credit card number",
];

type DocumentRow = { id: string; filename: string; format: string };
type Job = Awaited<ReturnType<typeof api.createRedactionJob>>;
type Review = Awaited<ReturnType<typeof api.getRedactionReview>>;
type Finding = Review["findings"][number];

export default function RedactionPage() {
  const [documents, setDocuments] = useState<DocumentRow[]>([]);
  const [documentId, setDocumentId] = useState("");
  const [categories, setCategories] = useState<string[]>([
    "person name",
    "employee number",
    "email address",
    "phone number",
    "street address",
    "salary",
    "government identification number",
    "driver license number",
  ]);
  const [customCategory, setCustomCategory] = useState("");
  const [instructions, setInstructions] = useState("");
  const [clarificationAnswer, setClarificationAnswer] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [pageNumber, setPageNumber] = useState(0);
  const [previewUrl, setPreviewUrl] = useState("");
  const [drawMode, setDrawMode] = useState(false);
  const [zoom, setZoom] = useState(100);
  const [boxDrafts, setBoxDrafts] = useState<Record<string, number[][]>>({});
  const [drawBox, setDrawBox] = useState<{ x: number; y: number; width: number; height: number } | null>(null);
  const [drawStart, setDrawStart] = useState<{ x: number; y: number } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [isUploading, setIsUploading] = useState(false);

  const page = review?.pages[pageNumber];
  const currentJobId = job?.id;
  const currentPageNumber = page?.number;
  const currentPageFailure = review?.failed_pages.find((failure) => failure.page_number === pageNumber);
  const pageFindings = useMemo(
    () => review?.findings.filter((finding) => finding.page_number === pageNumber) ?? [],
    [review?.findings, pageNumber],
  );
  const selectedCount = review?.findings.filter((finding) => finding.selected).length ?? 0;
  const supportedDocuments = documents.filter((document) =>
    SUPPORTED_FORMATS.includes(document.format),
  );

  useEffect(() => {
    let active = true;
    void api.getDocuments().then((result) => {
      if (active) setDocuments((current) => [
        ...current,
        ...result.documents.filter((document) => !current.some((item) => item.id === document.id)),
      ]);
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : "Could not load documents.");
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const jobId = new URLSearchParams(window.location.search).get("job_id");
    if (!jobId) return;
    let active = true;
    void api.getRedactionJob(jobId).then((loaded) => {
      if (!active) return;
      setJob(loaded);
      if (["review_ready", "approved", "exported"].includes(loaded.status)) {
        void api.getRedactionReview(jobId).then((loadedReview) => {
          if (active) setReview(loadedReview);
        }).catch((cause: unknown) => {
          if (active) setError(cause instanceof Error ? cause.message : "Could not load review.");
        });
      }
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : "Could not load redaction job.");
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!job || !["queued", "processing", "exporting"].includes(job.status)) return;
    let active = true;
    const timeout = window.setTimeout(() => {
      void api.getRedactionJob(job.id).then((next) => {
        if (!active) return;
        setJob(next);
        if (["review_ready", "approved", "exported"].includes(next.status)) {
          void api.getRedactionReview(job.id).then(setReview).catch((cause: unknown) => {
            if (active) setError(cause instanceof Error ? cause.message : "Could not load review.");
          });
        }
      }).catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : "Could not check job status.");
      });
    }, 1000);
    return () => { active = false; window.clearTimeout(timeout); };
  }, [job]);

  useEffect(() => {
    if (!currentJobId || currentPageNumber === undefined || !review) {
      setPreviewUrl("");
      return;
    }
    let active = true;
    let nextUrl = "";
    void api.getRedactionPreviewUrl(currentJobId, currentPageNumber).then((url) => {
      nextUrl = url;
      if (active) setPreviewUrl(url);
      else URL.revokeObjectURL(url);
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : "Could not load page preview.");
    });
    return () => {
      active = false;
      if (nextUrl) URL.revokeObjectURL(nextUrl);
    };
  }, [currentJobId, currentPageNumber, review]);

  const uploadSource = async (file: File) => {
    setError("");
    const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
    if (!SUPPORTED_FORMATS.includes(extension)) {
      setError("Choose a PDF or supported image file for redaction.");
      return;
    }
    if (file.size > MAX_FILE_SIZE) {
      setError(`File too large. Maximum size is ${MAX_FILE_SIZE / 1024 / 1024}MB.`);
      return;
    }
    setIsUploading(true);
    try {
      const uploaded = await api.uploadDocument(file);
      setDocuments((current) => [uploaded, ...current.filter((item) => item.id !== uploaded.id)]);
      setDocumentId(uploaded.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not upload the source document.");
    } finally {
      setIsUploading(false);
    }
  };

  const begin = async () => {
    if (!documentId || categories.length === 0) return;
    setError("");
    setBusy(true);
    setReview(null);
    try {
      const created = await api.createRedactionJob({ document_id: documentId, categories, instructions });
      setJob(created);
      window.history.replaceState(null, "", `/redaction?job_id=${created.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not start redaction.");
    } finally {
      setBusy(false);
    }
  };

  const updateFinding = async (
    finding: Finding,
    selected: boolean,
    boxes: number[][] = finding.boxes,
  ) => {
    if (!job || !review) return;
    setBusy(true);
    setError("");
    try {
      const nextJob = await api.updateRedactionFinding(job.id, finding.id, {
        selected,
        boxes,
      });
      setReview((current) => current && ({
        ...current,
        job: nextJob,
        findings: current.findings.map((item) => item.id === finding.id
          ? { ...item, selected, boxes }
          : item),
      }));
      setJob(nextJob);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not update this match.");
    } finally {
      setBusy(false);
    }
  };

  const submitClarification = async () => {
    if (!job || !clarificationAnswer.trim()) return;
    setBusy(true);
    setError("");
    try {
      const resumed = await api.clarifyRedactionJob(job.id, clarificationAnswer);
      setJob(resumed);
      setClarificationAnswer("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not submit clarification.");
    } finally {
      setBusy(false);
    }
  };

  const addCategory = () => {
    const value = customCategory.trim().toLocaleLowerCase();
    if (value && value.length <= 100 && !categories.includes(value)) {
      setCategories((current) => [...current, value]);
      setCustomCategory("");
    }
  };

  const approve = async () => {
    if (!job) return;
    setBusy(true);
    setError("");
    try {
      const approved = await api.approveRedactionReview(job.id, job.review_revision);
      setJob(approved);
      setReview((current) => current && ({ ...current, job: approved }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not approve review.");
    } finally {
      setBusy(false);
    }
  };

  const exportPdf = async () => {
    if (!job) return;
    setBusy(true);
    setError("");
    try {
      const exported = await api.exportRedactedDocument(job.id);
      setJob(exported);
      setReview((current) => current && ({ ...current, job: exported }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create the redacted PDF.");
    } finally {
      setBusy(false);
    }
  };

  const download = async () => {
    if (!job) return;
    try {
      const result = await api.downloadRedactedDocument(job.id);
      const url = URL.createObjectURL(result.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = result.filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not download the PDF.");
    }
  };

  const cancel = async () => {
    if (!job) return;
    try {
      const cancelled = await api.cancelRedactionJob(job.id);
      setJob(cancelled);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not cancel the job.");
    }
  };

  const retryPage = async () => {
    if (!job || currentPageNumber === undefined) return;
    setBusy(true);
    setError("");
    try {
      setJob(await api.retryRedactionPage(job.id, currentPageNumber));
      setReview(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not retry this page.");
    } finally {
      setBusy(false);
    }
  };

  const resolvePage = async () => {
    if (!job || currentPageNumber === undefined || !review) return;
    setBusy(true);
    setError("");
    try {
      const updatedJob = await api.resolveRedactionPage(job.id, currentPageNumber);
      setJob(updatedJob);
      setReview({
        ...review,
        job: updatedJob,
        failed_pages: review.failed_pages.map((failure) => failure.page_number === currentPageNumber
          ? { ...failure, manual_reviewed: true }
          : failure),
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not mark this page as inspected.");
    } finally {
      setBusy(false);
    }
  };

  const pointerPosition = (event: PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };

  const startDrawing = (event: PointerEvent<HTMLDivElement>) => {
    if (!drawMode) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const point = pointerPosition(event);
    setDrawStart(point);
    setDrawBox({ ...point, width: 0, height: 0 });
  };

  const moveDrawing = (event: PointerEvent<HTMLDivElement>) => {
    if (!drawStart || !drawMode) return;
    const point = pointerPosition(event);
    setDrawBox({
      x: Math.min(drawStart.x, point.x),
      y: Math.min(drawStart.y, point.y),
      width: Math.abs(point.x - drawStart.x),
      height: Math.abs(point.y - drawStart.y),
    });
  };

  const finishDrawing = async (event: PointerEvent<HTMLDivElement>) => {
    if (!drawStart || !job || !page) return;
    const point = pointerPosition(event);
    const rect = event.currentTarget.getBoundingClientRect();
    const x0 = Math.min(drawStart.x, point.x) / rect.width * page.width;
    const y0 = Math.min(drawStart.y, point.y) / rect.height * page.height;
    const x1 = Math.max(drawStart.x, point.x) / rect.width * page.width;
    const y1 = Math.max(drawStart.y, point.y) / rect.height * page.height;
    setDrawStart(null);
    setDrawBox(null);
    if (x1 - x0 < 2 || y1 - y0 < 2) return;
    try {
      const nextJob = await api.addRedactionBox(job.id, page.number, [x0, y0, x1, y1]);
      const nextReview = await api.getRedactionReview(job.id);
      setReview(nextReview);
      setJob(nextJob);
      setDrawMode(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not add a manual region.");
    }
  };

  return (
    <main className="container mx-auto max-w-6xl px-4 py-6 sm:p-8">
      <Link href="/documents" className="mb-5 inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" aria-hidden="true" /> Documents
      </Link>
      <div className="mb-6 flex items-center gap-3">
        <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-peach-soft text-peach-ink"><FileLock2 className="size-6" aria-hidden="true" /></span>
        <div>
          <h1 className="text-2xl font-bold">Document Redaction Agent</h1>
          <p className="mt-1 text-sm text-muted-foreground">Find sensitive details locally, review every region, then create a sanitized PDF.</p>
        </div>
      </div>

      {!job && <Card className="rounded-2xl">
        <CardHeader><CardTitle>Choose what to redact</CardTitle></CardHeader>
        <CardContent className="space-y-5">
          <div className="space-y-2">
            <label htmlFor="redaction-upload" className="text-sm font-medium">Upload a PDF or image</label>
            <Input
              id="redaction-upload"
              type="file"
              accept={SUPPORTED_FORMATS.map((format) => `.${format}`).join(",")}
              disabled={busy || isUploading}
              aria-describedby="redaction-upload-help"
              onChange={(event) => {
                const file = event.currentTarget.files?.[0];
                event.currentTarget.value = "";
                if (file) void uploadSource(file);
              }}
            />
            <p id="redaction-upload-help" className="text-xs text-muted-foreground">PDF, PNG, JPEG, TIFF, BMP or WebP (max {MAX_FILE_SIZE / 1024 / 1024}MB). Uploaded files are saved in Documents and selected below.</p>
            {isUploading && <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground"><LoaderCircle className="size-4 animate-spin" aria-hidden="true" /> Uploading...</p>}
          </div>
          <label className="block space-y-2 text-sm font-medium">Source document
            <select className="h-11 w-full rounded-xl border bg-background px-3" value={documentId} disabled={busy || isUploading} onChange={(event) => setDocumentId(event.target.value)}>
              <option value="">Select a PDF or image</option>
              {supportedDocuments.map((document) => <option key={document.id} value={document.id}>{document.filename}</option>)}
            </select>
          </label>
          <fieldset>
            <legend className="mb-2 text-sm font-medium">Categories</legend>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from(new Set([...CATEGORY_OPTIONS, ...categories])).map((category) => (
                <label key={category} className="flex items-center gap-2 rounded-xl border px-3 py-2 text-sm">
                  <input type="checkbox" checked={categories.includes(category)} onChange={(event) => setCategories((current) => event.target.checked ? [...current, category] : current.filter((item) => item !== category))} />
                  <span className="capitalize">{category}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <div className="flex gap-2">
            <Input value={customCategory} maxLength={100} onChange={(event) => setCustomCategory(event.target.value)} placeholder="Add a custom field, e.g. project code" aria-label="Custom redaction category" />
            <Button type="button" variant="outline" onClick={addCategory} disabled={!customCategory.trim()}><Plus className="mr-1 size-4" /> Add field</Button>
          </div>
          <label className="block space-y-2 text-sm font-medium">Additional instructions
            <Textarea value={instructions} maxLength={2000} onChange={(event) => setInstructions(event.target.value)} placeholder="Optional: redact the employee's name but keep the manager's name." rows={3} />
          </label>
          <div className="flex items-start gap-2 rounded-xl bg-muted/60 p-3 text-sm text-muted-foreground">
            <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <p>Detection runs on this device. Review every page before export; automated detection can miss sensitive content.</p>
          </div>
          {supportedDocuments.length === 0 && <p className="text-sm text-muted-foreground">Upload a PDF or image above to get started.</p>}
          <Button onClick={begin} disabled={!documentId || categories.length === 0 || busy || isUploading}>
            {busy ? <LoaderCircle className="mr-2 size-4 animate-spin" /> : <FileLock2 className="mr-2 size-4" />}
            Analyze document
          </Button>
        </CardContent>
      </Card>}

      {job && <div className="space-y-5">
        <Card className="rounded-2xl">
          <CardContent className="flex flex-wrap items-center justify-between gap-4 pt-6">
            <div>
              <div className="flex items-center gap-2"><Badge variant="secondary" className="capitalize">{job.status.replaceAll("_", " ")}</Badge>{job.page_count > 0 && <span className="text-sm text-muted-foreground">{job.pages_processed} of {job.page_count} pages</span>}</div>
              {job.status === "processing" || job.status === "queued" ? <p className="mt-2 text-sm text-muted-foreground">Scanning locally for requested information…</p> : null}
              {job.error_message && <p className="mt-2 text-sm text-destructive">{job.error_message}</p>}
            </div>
            <div className="flex flex-wrap gap-2">
              {(["queued", "processing", "needs_clarification"].includes(job.status)) && <Button variant="outline" onClick={cancel}><X className="mr-2 size-4" /> Cancel</Button>}
              {job.status === "approved" && <Button onClick={exportPdf} disabled={busy}>{busy ? <LoaderCircle className="mr-2 size-4 animate-spin" /> : <FileLock2 className="mr-2 size-4" />} Create redacted PDF</Button>}
              {job.status === "exported" && <Button onClick={download}><Download className="mr-2 size-4" /> Download redacted PDF</Button>}
              <Button variant="ghost" onClick={() => {
                setJob(null);
                setReview(null);
                setPageNumber(0);
                setClarificationAnswer("");
                setError("");
                window.history.replaceState(null, "", "/redaction");
              }}>New job</Button>
            </div>
          </CardContent>
        </Card>

        {job.status === "needs_clarification" && <Card className="rounded-2xl">
          <CardHeader><CardTitle>Clarify your redaction request</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm">{job.clarification_question ?? "Please clarify which matching content should be redacted."}</p>
            <label className="block space-y-2 text-sm font-medium">Your answer
              <Textarea value={clarificationAnswer} maxLength={1_000} onChange={(event) => setClarificationAnswer(event.target.value)} rows={2} />
            </label>
            <Button onClick={submitClarification} disabled={busy || !clarificationAnswer.trim()}>
              {busy && <LoaderCircle className="mr-2 size-4 animate-spin" />} Continue analysis
            </Button>
          </CardContent>
        </Card>}

        {review && page && <div className="grid gap-5 lg:grid-cols-[minmax(0,1.5fr)_minmax(280px,0.8fr)]">
          <Card className="overflow-hidden rounded-2xl">
            <CardHeader className="flex flex-row items-center justify-between space-y-0">
              <CardTitle>Page {pageNumber + 1} <span className="font-normal text-muted-foreground">of {review.pages.length}</span></CardTitle>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="icon" aria-label="Previous page" disabled={pageNumber === 0} onClick={() => setPageNumber((number) => number - 1)}><ArrowLeft className="size-4" /></Button>
                <Button variant="outline" size="icon" aria-label="Next page" disabled={pageNumber + 1 >= review.pages.length} onClick={() => setPageNumber((number) => number + 1)}><ArrowRight className="size-4" /></Button>
                <Button variant="outline" size="icon" aria-label="Zoom out" disabled={zoom <= 50} onClick={() => setZoom((value) => Math.max(50, value - 25))}>−</Button>
                <span className="w-12 text-center text-xs tabular-nums">{zoom}%</span>
                <Button variant="outline" size="icon" aria-label="Zoom in" disabled={zoom >= 200} onClick={() => setZoom((value) => Math.min(200, value + 25))}>+</Button>
                <Button variant={drawMode ? "default" : "outline"} onClick={() => setDrawMode((active) => !active)}><Square className="mr-2 size-4" /> {drawMode ? "Drawing on" : "Add region"}</Button>
              </div>
            </CardHeader>
            <CardContent>
              <div className="max-h-[70vh] overflow-auto rounded-lg border bg-muted/30">
              <div
                className={`relative mx-auto ${drawMode ? "cursor-crosshair touch-none" : ""}`}
                style={{ width: `${zoom}%` }}
                onPointerDown={startDrawing}
                onPointerMove={moveDrawing}
                onPointerUp={(event) => { void finishDrawing(event); }}
              >
                {/* Authenticated, short-lived blob preview; next/image cannot optimize it. */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                {previewUrl && <img src={previewUrl} alt={`Source document page ${pageNumber + 1}`} className="block h-auto w-full select-none" draggable={false} />}
                {pageFindings.flatMap((finding) => finding.boxes.map((box, index) => (
                  <div key={`${finding.id}-${index}`} className={`pointer-events-none absolute border-2 ${finding.selected ? "border-red-600 bg-red-500/15" : "border-amber-500 border-dashed bg-amber-400/10"}`} style={{ left: `${box[0]! / page.width * 100}%`, top: `${box[1]! / page.height * 100}%`, width: `${(box[2]! - box[0]!) / page.width * 100}%`, height: `${(box[3]! - box[1]!) / page.height * 100}%` }} />
                )))}
                {drawBox && <div className="pointer-events-none absolute border-2 border-primary bg-primary/20" style={{ left: drawBox.x, top: drawBox.y, width: drawBox.width, height: drawBox.height }} />}
              </div>
              </div>
              <p className="mt-3 text-xs text-muted-foreground">Red boxes are selected for redaction. Amber boxes are excluded. Drag on the page to add a manual region.</p>
              {currentPageFailure && <div role="alert" className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
                <p>{currentPageFailure.error}</p>
                <p className="mt-1">This page was not scanned. Review it visually; draw a redaction region if needed.</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button type="button" variant="outline" disabled={busy} onClick={retryPage}>Retry page</Button>
                  {!currentPageFailure.manual_reviewed
                    ? <Button type="button" disabled={busy} onClick={resolvePage}>I inspected this page</Button>
                    : <Badge variant="secondary">Manually inspected</Badge>}
                </div>
              </div>}
            </CardContent>
          </Card>

          <Card className="rounded-2xl">
            <CardHeader><CardTitle className="flex items-center justify-between">Detected regions <Badge variant="secondary">{selectedCount} selected</Badge></CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {review.job.warnings.map((warning) => <div key={warning} className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{warning}</div>)}
              {pageFindings.length === 0 ? <p className="text-sm text-muted-foreground">{currentPageFailure ? "Automatic scanning did not finish on this page. Inspect the page and add any needed regions manually." : "No matches were found on this page. You can draw a region to redact it manually."}</p> : pageFindings.map((finding) => (
                <label key={finding.id} className="flex cursor-pointer items-start gap-3 rounded-xl border p-3">
                  <input className="mt-1" type="checkbox" checked={finding.selected} disabled={busy || job.status === "exported"} onChange={(event) => { void updateFinding(finding, event.target.checked); }} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2"><Badge variant="outline" className="capitalize">{finding.category}</Badge><span className="text-xs text-muted-foreground">{finding.source}{finding.confidence !== null ? ` · ${Math.round(finding.confidence * 100)}%` : ""}</span></span>
                    <span className="mt-2 block break-words font-mono text-sm">{finding.text}</span>
                    <details className="mt-2">
                      <summary className="cursor-pointer text-xs text-muted-foreground">Adjust box coordinates</summary>
                      <div className="mt-2 space-y-2">
                        {finding.boxes.map((box, boxIndex) => (
                          <div key={boxIndex} className="grid grid-cols-4 gap-1">
                            {box.map((coordinate, coordinateIndex) => (
                              <Input
                                key={coordinateIndex}
                                type="number"
                                aria-label={`${finding.category} box ${boxIndex + 1} coordinate ${["left", "top", "right", "bottom"][coordinateIndex]}`}
                                value={(boxDrafts[finding.id] ?? finding.boxes)[boxIndex]?.[coordinateIndex] ?? coordinate}
                                onChange={(event) => setBoxDrafts((drafts) => {
                                  const next = (drafts[finding.id] ?? finding.boxes).map((item) => [...item]);
                                  const currentBox = next[boxIndex];
                                  if (currentBox) currentBox[coordinateIndex] = Number(event.target.value);
                                  return { ...drafts, [finding.id]: next };
                                })}
                                className="h-8 px-2 text-xs"
                              />
                            ))}
                          </div>
                        ))}
                        <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => {
                          void updateFinding(finding, finding.selected, boxDrafts[finding.id] ?? finding.boxes);
                        }}>Save box</Button>
                      </div>
                    </details>
                  </span>
                </label>
              ))}
              {job.status !== "exported" && <div className="space-y-2 border-t pt-4">
                <p className="text-xs text-muted-foreground">Human review is required before a PDF can be produced.</p>
                {review.failed_pages.some((failure) => !failure.manual_reviewed) && <p className="text-sm text-amber-700">Retry or manually inspect every failed page before approval.</p>}
                <Button className="w-full" onClick={approve} disabled={busy || selectedCount === 0 || review.failed_pages.some((failure) => !failure.manual_reviewed) || job.status === "approved"}>
                  <Check className="mr-2 size-4" /> Approve {selectedCount} selected regions
                </Button>
                {job.status === "approved" && <p className="text-center text-xs text-muted-foreground">Current review approved. Create the sanitized PDF when ready.</p>}
              </div>}
            </CardContent>
          </Card>
        </div>}
      </div>}
      {error && <div role="alert" className="mt-4 rounded-xl bg-destructive/10 p-3 text-sm text-destructive">{error}</div>}
    </main>
  );
}
