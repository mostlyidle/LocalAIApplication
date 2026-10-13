"""Public status shapes for the per-user GitHub App connection."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic resolves response types at runtime.

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.action_item_schemas import ActionItemSuggestion  # noqa: TC001


class GitHubConnectionResponse(BaseModel):
    """Connection status without exposing any credential material."""

    configured: bool
    connected: bool
    login: str | None = None
    expires_at: datetime | None = None
    install_url: str | None = None


class GitHubAuthorizationResponse(BaseModel):
    """Authorization URL returned to the signed-in browser."""

    authorization_url: str


class GitHubRepositoryResponse(BaseModel):
    """Safe repository metadata and this account's explicit selection state."""

    repository_id: str
    full_name: str
    html_url: str
    default_branch: str
    is_private: bool
    selected: bool


class GitHubRepositoryListResponse(BaseModel):
    repositories: list[GitHubRepositoryResponse]


class GitHubRepositorySelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected: bool = Field()


class GitHubProjectIssue(BaseModel):
    number: int
    title: str
    body: str
    state: str
    html_url: str
    author: str | None
    updated_at: str | None
    labels: list[str]


class GitHubProjectPullRequest(GitHubProjectIssue):
    draft: bool
    head_sha: str | None


class GitHubProjectOverviewResponse(BaseModel):
    repository_id: str
    repository: str
    issues: list[GitHubProjectIssue]
    pull_requests: list[GitHubProjectPullRequest]


class GitHubPullFile(BaseModel):
    filename: str
    status: str
    additions: int
    deletions: int
    patch: str | None
    html_url: str | None


class GitHubCheckRun(BaseModel):
    name: str
    status: str
    conclusion: str | None
    html_url: str | None


class GitHubPullDetailResponse(BaseModel):
    repository_id: str
    number: int
    title: str
    body: str
    state: str
    html_url: str
    head_sha: str | None
    files: list[GitHubPullFile]
    checks: list[GitHubCheckRun]
    files_truncated: bool
    checks_truncated: bool


class GitHubIssueProposalResponse(BaseModel):
    repository_id: str
    source_id: str
    source_title: str
    suggestions: list[ActionItemSuggestion]


class GitHubIssueCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=256)
    body: str = Field(default="", max_length=10_000)

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Issue title cannot be blank.")
        return value


class GitHubCommentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=10_000)

    @field_validator("body")
    @classmethod
    def nonblank_body(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Comment cannot be blank.")
        return value


class GitHubIssueWriteResponse(BaseModel):
    number: int
    title: str
    html_url: str


class GitHubCommentWriteResponse(BaseModel):
    id: str
    html_url: str | None
