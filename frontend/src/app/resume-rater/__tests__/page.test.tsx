import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const api = vi.hoisted(() => ({
  getResumeRaterWorkspaces: vi.fn(),
  getResumeRaterWorkspace: vi.fn(),
  createResumeRaterWorkspace: vi.fn(),
  createResumeRaterRevision: vi.fn(),
  updateResumeRaterRubric: vi.fn(),
  approveResumeRaterRubric: vi.fn(),
  retryResumeRaterRubric: vi.fn(),
  cancelResumeRaterRubric: vi.fn(),
  uploadResumeRaterCandidates: vi.fn(),
  renameResumeRaterCandidate: vi.fn(),
  retryResumeRaterCandidate: vi.fn(),
  cancelResumeRaterCandidate: vi.fn(),
  deleteResumeRaterCandidate: vi.fn(),
  deleteResumeRaterWorkspace: vi.fn(),
}));

vi.mock("@/lib/api", () => api);
vi.mock("lucide-react", () => {
  const icon = (props: Record<string, unknown>) => <svg aria-hidden="true" {...props} />;
  return {
    AlertTriangle: icon,
    ArrowUpRight: icon,
    BriefcaseBusiness: icon,
    Check: icon,
    ChevronDown: icon,
    CircleHelp: icon,
    FileText: icon,
    Loader2: icon,
    Pencil: icon,
    Plus: icon,
    Printer: icon,
    RefreshCw: icon,
    ShieldCheck: icon,
    Sparkles: icon,
    Trash2: icon,
    Upload: icon,
    X: icon,
  };
});

import ResumeRaterPage from "@/app/resume-rater/page";
import type { ResumeRaterWorkspaceDetail } from "@/lib/schemas";

const criteria = [
  { id: "experience", label: "Relevant experience", description: "Experience in similar roles.", weight: 50, must_have: false },
  { id: "skills", label: "Technical skills", description: "Required languages and tools.", weight: 30, must_have: false },
  { id: "leadership", label: "Team leadership", description: "Required team leadership evidence.", weight: 20, must_have: true },
];

function makeWorkspace(status = "approved"): ResumeRaterWorkspaceDetail {
  return {
    id: "workspace-1",
    title: "Senior engineer",
    current_revision: 1,
    revision_status: status,
    candidate_count: 1,
    created_at: "2026-10-19T12:00:00Z",
    updated_at: "2026-10-19T12:00:00Z",
    revisions: [{
      id: "revision-1",
      version: 1,
      job_posting: "A senior engineering role with relevant systems experience. ".repeat(3),
      criteria,
      status,
      error_message: null,
      created_at: "2026-10-19T12:00:00Z",
    }],
    candidates: [{
      id: "candidate-1",
      display_name: "Candidate One",
      filename: "candidate-one.pdf",
      created_at: "2026-10-19T12:00:00Z",
      current_assessment: {
        id: "assessment-1",
        revision_version: 1,
        status: "completed",
        score: 82,
        rank: 1,
        must_haves_not_met: ["leadership"],
        error_message: null,
        created_at: "2026-10-19T12:00:00Z",
        completed_at: "2026-10-19T12:01:00Z",
        result: {
          summary: "Strong engineering evidence; leadership needs follow-up.",
          criterion_scores: [
            { criterion_id: "experience", level: "fully_meets", explanation: "Direct experience.", evidence_quotes: ["Built reliable systems."] },
            { criterion_id: "skills", level: "substantial", explanation: "The required tools are listed.", evidence_quotes: ["Used Python and SQL."] },
            { criterion_id: "leadership", level: "partial", explanation: "Mentoring is mentioned.", evidence_quotes: ["Mentored two engineers."] },
          ],
          strengths: [{ criterion_id: "experience", text: "Relevant systems experience.", evidence_quotes: ["Built reliable systems."] }],
          gaps: [{ criterion_id: "leadership", text: "Clarify the scope of leadership.", evidence_quotes: ["Mentored two engineers."] }],
          interview_questions: ["What was your role in leading this work?"],
          resume_suggestions: [{ text: "Clarify the specific contribution.", source_quote: "Mentored two engineers." }],
        },
      },
      history: [],
    }],
  };
}

function addPreviousRevision(
  workspace: ResumeRaterWorkspaceDetail,
  currentStatus: "completed" | "queued" = "completed",
): ResumeRaterWorkspaceDetail {
  const candidate = workspace.candidates[0];
  const currentAssessment = candidate?.current_assessment;
  if (!candidate || !currentAssessment?.result) {
    throw new Error("Expected a completed candidate assessment.");
  }
  const currentCriteria = workspace.revisions[0].criteria ?? [];
  const previousAssessment = {
    ...currentAssessment,
    id: "assessment-old",
    revision_version: 1,
    score: 71,
    result: {
      ...currentAssessment.result,
      summary: "Previous revision summary.",
      criterion_scores: currentAssessment.result.criterion_scores.map((score) => ({
        ...score,
        explanation: "Previous rubric evidence explanation.",
        evidence_quotes: ["Previous exact resume quote."],
      })),
    },
  };
  workspace.current_revision = 2;
  workspace.revisions[0].criteria = currentCriteria.map((criterion) => ({
    ...criterion,
    label: `Previous ${criterion.label}`,
  }));
  workspace.revisions.push({
    ...workspace.revisions[0],
    id: "revision-2",
    version: 2,
    criteria: currentCriteria.map((criterion) => ({ ...criterion })),
  });
  const nextCurrentAssessment = {
    ...currentAssessment,
    id: "assessment-current",
    revision_version: 2,
    status: currentStatus,
    score: currentStatus === "completed" ? currentAssessment.score : null,
    rank: currentStatus === "completed" ? currentAssessment.rank : null,
    must_haves_not_met: currentStatus === "completed" ? currentAssessment.must_haves_not_met : [],
    result: currentStatus === "completed" ? currentAssessment.result : null,
  };
  candidate.current_assessment = nextCurrentAssessment;
  candidate.history = [previousAssessment, nextCurrentAssessment];
  return workspace;
}

describe("ResumeRaterPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getResumeRaterWorkspaces.mockResolvedValue([]);
    api.getResumeRaterWorkspace.mockResolvedValue(makeWorkspace());
  });

  it("starts a job workspace from a pasted job posting", async () => {
    api.createResumeRaterWorkspace.mockResolvedValue({
      ...makeWorkspace("rubric_queued"),
      candidate_count: 0,
      candidates: [],
    });
    render(<ResumeRaterPage />);

    fireEvent.change(await screen.findByLabelText("Job title"), { target: { value: "Senior engineer" } });
    const postingField = screen.getByLabelText("Job posting");
    expect(postingField).toHaveAttribute("rows", "20");
    expect(postingField).toHaveClass("field-sizing-fixed");
    expect(postingField).not.toHaveClass("field-sizing-content");
    fireEvent.change(postingField, {
      target: { value: "A senior engineering role with more than one hundred characters in the complete job posting, including desired skills and responsibilities. " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Prepare job rubric" }));

    await waitFor(() => {
      expect(api.createResumeRaterWorkspace).toHaveBeenCalledWith({
        title: "Senior engineer",
        job_posting: "A senior engineering role with more than one hundred characters in the complete job posting, including desired skills and responsibilities.",
      });
    });
    expect(await screen.findByText("Preparing a suggested rubric")).toBeInTheDocument();
  });

  it("shows ranked evidence, must-have flags, suggestions and interview questions", async () => {
    const workspace = makeWorkspace();
    api.getResumeRaterWorkspaces.mockResolvedValue([workspace]);
    api.getResumeRaterWorkspace.mockResolvedValue(workspace);
    render(<ResumeRaterPage />);

    expect(await screen.findByText("Candidate One")).toBeInTheDocument();
    expect(screen.getByText("82/100")).toBeInTheDocument();
    expect(screen.getByText("Rank #1")).toBeInTheDocument();
    fireEvent.click(screen.getByText("View evidence and assessment history"));

    expect(await screen.findByText("Must-haves below the evidence threshold")).toBeInTheDocument();
    expect(screen.getAllByText("Team leadership").length).toBeGreaterThan(0);
    expect(screen.getByText("Strong engineering evidence; leadership needs follow-up.")).toBeInTheDocument();
    expect(screen.getByText("Clarify the specific contribution.")).toBeInTheDocument();
    expect(screen.getByText("What was your role in leading this work?")).toBeInTheDocument();
  });

  it("keeps prior revision rubrics and full assessment evidence reviewable", async () => {
    const workspace = addPreviousRevision(makeWorkspace());
    api.getResumeRaterWorkspaces.mockResolvedValue([workspace]);
    api.getResumeRaterWorkspace.mockResolvedValue(workspace);

    render(<ResumeRaterPage />);
    fireEvent.click(await screen.findByText("View evidence and assessment history"));
    fireEvent.click(screen.getByText("Previous job and rubric revisions"));
    expect(screen.getByText("Previous Relevant experience · 50%" )).toBeInTheDocument();
    fireEvent.click(screen.getByText("Previous assessments (1)"));
    fireEvent.click(screen.getByText("View evidence and recommendations"));

    expect((await screen.findAllByText("Previous rubric evidence explanation.")).length).toBe(3);
    expect(screen.getAllByText((_, element) => (
      element?.textContent?.includes("Previous exact resume quote.") ?? false
    )).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Previous Team leadership").length).toBeGreaterThan(0);
  });

  it("shows previous reports while the current revision is being assessed", async () => {
    const workspace = addPreviousRevision(makeWorkspace(), "queued");
    api.getResumeRaterWorkspaces.mockResolvedValue([workspace]);
    api.getResumeRaterWorkspace.mockResolvedValue(workspace);
    render(<ResumeRaterPage />);

    fireEvent.click(await screen.findByText("View evidence and assessment history"));
    fireEvent.click(screen.getByText("Previous assessments (1)"));
    fireEvent.click(screen.getByText("View evidence and recommendations"));

    expect(await screen.findByText("Previous revision summary.")).toBeInTheDocument();
    expect((await screen.findAllByText("Previous rubric evidence explanation.")).length).toBe(3);
  });

  it("keeps the latest selected workspace when an older request resolves late", async () => {
    const first = makeWorkspace();
    const second = makeWorkspace();
    second.id = "workspace-2";
    second.title = "Second job";
    api.getResumeRaterWorkspaces.mockResolvedValue([first, second]);
    api.getResumeRaterWorkspace.mockResolvedValue(first);
    render(<ResumeRaterPage />);
    await screen.findByText("Candidate One");

    let resolveFirstRequest: (workspace: ResumeRaterWorkspaceDetail) => void = () => {};
    api.getResumeRaterWorkspace.mockImplementation((id: string) => id === first.id
      ? new Promise((resolve) => { resolveFirstRequest = resolve; })
      : Promise.resolve(second));

    fireEvent.click(screen.getByRole("button", { name: /Second job/ }));
    const secondJobButton = screen.getByRole("button", { name: /Second job/ });
    await waitFor(() => expect(secondJobButton).toHaveAttribute("aria-current", "page"));

    fireEvent.click(screen.getByRole("button", { name: /Senior engineer/ }));
    fireEvent.click(secondJobButton);
    await waitFor(() => expect(secondJobButton).toHaveAttribute("aria-current", "page"));
    resolveFirstRequest(first);

    await waitFor(() => expect(secondJobButton).toHaveAttribute("aria-current", "page"));
    expect(screen.getByRole("button", { name: /Senior engineer/ })).not.toHaveAttribute("aria-current", "page");
  });
});
