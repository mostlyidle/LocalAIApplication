"""Per-account GitHub App authorization endpoints."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select

from app.api.middleware.rate_limiting import limiter
from app.config import settings
from app.dependencies import get_authenticated_session, get_db
from app.models.db_models import GitHubConnection, GitHubOAuthState, GitHubRepositorySelection
from app.models.github_schemas import (
    GitHubAuthorizationResponse,
    GitHubCheckRun,
    GitHubCommentCreateRequest,
    GitHubCommentWriteResponse,
    GitHubConnectionResponse,
    GitHubIssueCreateRequest,
    GitHubIssueProposalResponse,
    GitHubIssueWriteResponse,
    GitHubProjectIssue,
    GitHubProjectOverviewResponse,
    GitHubProjectPullRequest,
    GitHubPullDetailResponse,
    GitHubPullFile,
    GitHubRepositoryListResponse,
    GitHubRepositoryResponse,
    GitHubRepositorySelectionRequest,
)
from app.services.auth import AuthenticatedSession, resolve_session_by_id  # noqa: TC001
from app.services.github_oauth import (
    GitHubIntegrationError,
    decrypt_token,
    encrypt_token,
    github_oauth_client,
    is_github_configured,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.get("/github/connection", response_model=GitHubConnectionResponse)
async def github_connection_status(
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> GitHubConnectionResponse:
    """Return safe GitHub connection status for the current account."""
    connection = await db.scalar(
        select(GitHubConnection).where(GitHubConnection.owner_id == authenticated.account.id)
    )
    slug = settings.github_app_slug
    install_url = f"https://github.com/apps/{quote(slug, safe='')}/installations/new" if slug else None
    return GitHubConnectionResponse(
        configured=is_github_configured(),
        connected=connection is not None,
        login=connection.github_login if connection else None,
        expires_at=connection.expires_at if connection else None,
        install_url=install_url,
    )


@router.post("/github/connect", response_model=GitHubAuthorizationResponse)
async def start_github_authorization(
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> GitHubAuthorizationResponse:
    """Create one-time OAuth state tied to this account and browser session."""
    if not is_github_configured():
        raise GitHubIntegrationError("GitHub connection is not configured on this server.", 503)
    encrypt_token("configuration-check")
    raw_state = secrets.token_urlsafe(32)
    state_hash = hashlib.sha256(raw_state.encode("utf-8")).hexdigest()
    await db.execute(delete(GitHubOAuthState).where(GitHubOAuthState.expires_at < datetime.now(UTC)))
    db.add(
        GitHubOAuthState(
            state_hash=state_hash,
            owner_id=authenticated.account.id,
            session_id=authenticated.session.id,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
    )
    await db.commit()
    authorization_url = github_oauth_client.authorization_url(raw_state)
    return GitHubAuthorizationResponse(authorization_url=authorization_url)


@router.get("/github/callback")
async def finish_github_authorization(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> RedirectResponse:
    """Consume OAuth state, recheck its initiating login, then save encrypted tokens."""
    if not state:
        raise HTTPException(status_code=400, detail="GitHub authorization state is missing.")
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    record = await db.get(GitHubOAuthState, state_hash)
    if record is None or record.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC):
        raise HTTPException(status_code=400, detail="GitHub authorization state is invalid or expired.")
    authenticated = await resolve_session_by_id(db, record.session_id)
    if authenticated is None or authenticated.account.id != record.owner_id:
        await db.delete(record)
        await db.commit()
        raise HTTPException(status_code=401, detail="The sign-in session expired; connect again.")
    await db.delete(record)
    await db.commit()

    result = "denied"
    if not error:
        if not code:
            raise HTTPException(status_code=400, detail="GitHub authorization code is missing.")
        token_set, user_id, login = await github_oauth_client.exchange_code(code)
        connection = await db.scalar(
            select(GitHubConnection).where(GitHubConnection.owner_id == record.owner_id)
        )
        if connection is None:
            connection = GitHubConnection(owner_id=record.owner_id)
            db.add(connection)
        connection.github_user_id = user_id
        connection.github_login = login
        connection.encrypted_access_token = encrypt_token(token_set.access_token)
        connection.encrypted_refresh_token = encrypt_token(token_set.refresh_token)
        connection.expires_at = token_set.expires_at.replace(tzinfo=None)
        connection.refresh_expires_at = token_set.refresh_expires_at.replace(tzinfo=None)
        await db.commit()
        result = "connected"

    return RedirectResponse(
        f"{settings.github_frontend_url.rstrip('/')}/settings?github={result}",
        status_code=303,
    )


@router.delete("/github/connection", status_code=204)
async def disconnect_github(
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> None:
    """Revoke the user's GitHub App grant and then erase locally stored tokens."""
    connection = await db.scalar(
        select(GitHubConnection).where(GitHubConnection.owner_id == authenticated.account.id)
    )
    if connection is None:
        return
    await github_oauth_client.revoke(decrypt_token(connection.encrypted_access_token))
    await db.execute(
        delete(GitHubRepositorySelection).where(
            GitHubRepositorySelection.owner_id == authenticated.account.id
        )
    )
    await db.delete(connection)
    await db.commit()


async def _connected_github(owner_id: str, db: AsyncSession) -> tuple[GitHubConnection, str]:
    connection = await db.scalar(
        select(GitHubConnection).where(GitHubConnection.owner_id == owner_id)
    )
    if connection is None:
        raise HTTPException(status_code=409, detail="Connect a GitHub account first.")
    token = await github_oauth_client.access_token(connection, db)
    return connection, token


async def _accessible_repositories(token: str) -> list[dict[str, object]]:
    """Enumerate a bounded set of repositories visible to the authorized user."""
    repositories: list[dict[str, object]] = []
    for page in range(1, 11):
        payload = await github_oauth_client.api_get_json(
            "/user/repos",
            token,
            {
                "affiliation": "owner,collaborator,organization_member",
                "sort": "full_name",
                "per_page": 100,
                "page": page,
            },
        )
        if not isinstance(payload, list):
            raise GitHubIntegrationError("GitHub returned an invalid repository list.")
        for item in payload:
            if not isinstance(item, dict):
                continue
            repo_id, full_name, html_url = (
                item.get("id"),
                item.get("full_name"),
                item.get("html_url"),
            )
            branch = item.get("default_branch")
            if (
                isinstance(repo_id, int)
                and isinstance(full_name, str)
                and isinstance(html_url, str)
                and isinstance(branch, str)
            ):
                repositories.append(
                    {
                        "repository_id": str(repo_id),
                        "full_name": full_name[:256],
                        "html_url": html_url,
                        "default_branch": branch[:256],
                        "is_private": item.get("private") is True,
                    }
                )
        if len(payload) < 100:
            return repositories
    raise GitHubIntegrationError(
        "GitHub returned too many repositories to safely enumerate; narrow the app installation.",
        413,
    )


@router.get("/github/repositories", response_model=GitHubRepositoryListResponse)
async def list_github_repositories(
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> GitHubRepositoryListResponse:
    """List accessible repositories and mark those explicitly selected by this account."""
    _, token = await _connected_github(authenticated.account.id, db)
    accessible = await _accessible_repositories(token)
    rows = await db.scalars(
        select(GitHubRepositorySelection).where(
            GitHubRepositorySelection.owner_id == authenticated.account.id
        )
    )
    selected_ids = {row.repository_id for row in rows.all()}
    return GitHubRepositoryListResponse(
        repositories=[
            GitHubRepositoryResponse(**repo, selected=repo["repository_id"] in selected_ids)
            for repo in accessible
        ]
    )


@router.put("/github/repositories/{repository_id}/selection", status_code=204)
async def set_github_repository_selection(
    body: GitHubRepositorySelectionRequest,
    repository_id: str = Path(pattern=r"^[0-9]{1,32}$"),
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> None:
    """Select only repos currently visible to this account's GitHub authorization."""
    _, token = await _connected_github(authenticated.account.id, db)
    selected = await db.scalar(
        select(GitHubRepositorySelection).where(
            GitHubRepositorySelection.owner_id == authenticated.account.id,
            GitHubRepositorySelection.repository_id == repository_id,
        )
    )
    if not body.selected:
        if selected is not None:
            await db.delete(selected)
            await db.commit()
        return

    accessible = await _accessible_repositories(token)
    repository = next((repo for repo in accessible if repo["repository_id"] == repository_id), None)
    if repository is None:
        raise HTTPException(
            status_code=404, detail="Repository is not available to this GitHub account."
        )
    if selected is None:
        selected = GitHubRepositorySelection(
            owner_id=authenticated.account.id,
            repository_id=repository_id,
            full_name=str(repository["full_name"]),
            html_url=str(repository["html_url"]),
            default_branch=str(repository["default_branch"]),
            is_private=bool(repository["is_private"]),
        )
        db.add(selected)
    else:
        selected.full_name = str(repository["full_name"])
        selected.html_url = str(repository["html_url"])
        selected.default_branch = str(repository["default_branch"])
        selected.is_private = bool(repository["is_private"])
    await db.commit()


async def _selected_repository(
    owner_id: str, repository_id: str, db: AsyncSession
) -> tuple[GitHubRepositorySelection, str, str]:
    repository = await db.scalar(
        select(GitHubRepositorySelection).where(
            GitHubRepositorySelection.owner_id == owner_id,
            GitHubRepositorySelection.repository_id == repository_id,
        )
    )
    if repository is None:
        raise HTTPException(status_code=404, detail="Select this repository in Settings first.")
    connection, token = await _connected_github(owner_id, db)
    parts = repository.full_name.split("/")
    if len(parts) != 2 or any(not part for part in parts):
        raise GitHubIntegrationError("Stored GitHub repository metadata is invalid.", 503)
    path = f"/repos/{quote(parts[0], safe='')}/{quote(parts[1], safe='')}"
    return repository, token, path


def _github_issue_shape(payload: object) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        return None
    number, title, url = payload.get("number"), payload.get("title"), payload.get("html_url")
    if not isinstance(number, int) or not isinstance(title, str) or not isinstance(url, str):
        return None
    author = payload.get("user")
    labels = payload.get("labels")
    return {
        "number": number,
        "title": title[:300],
        "body": payload.get("body")[:4_000] if isinstance(payload.get("body"), str) else "",
        "state": str(payload.get("state", "open"))[:20],
        "html_url": url,
        "author": author.get("login") if isinstance(author, dict) and isinstance(author.get("login"), str) else None,
        "updated_at": payload.get("updated_at") if isinstance(payload.get("updated_at"), str) else None,
        "labels": [label["name"][:100] for label in labels if isinstance(label, dict) and isinstance(label.get("name"), str)][:20]
        if isinstance(labels, list)
        else [],
    }


async def _list_github_items(path: str, token: str, *, issues: bool) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for page in range(1, 6):
        payload = await github_oauth_client.api_get_json(
            f"{path}/{'issues' if issues else 'pulls'}",
            token,
            {"state": "open", "sort": "updated", "direction": "desc", "per_page": 100, "page": page},
        )
        if not isinstance(payload, list):
            raise GitHubIntegrationError("GitHub returned an invalid project item list.")
        for item in payload:
            if issues and isinstance(item, dict) and "pull_request" in item:
                continue
            shaped = _github_issue_shape(item)
            if shaped is None:
                continue
            if not issues:
                head = item.get("head") if isinstance(item, dict) else None
                shaped["draft"] = item.get("draft") is True if isinstance(item, dict) else False
                shaped["head_sha"] = head.get("sha") if isinstance(head, dict) and isinstance(head.get("sha"), str) else None
            items.append(shaped)
        if len(payload) < 100:
            return items
    raise GitHubIntegrationError("GitHub returned too many open project items; narrow the query.", 413)


@router.get("/github/agent/repositories/{repository_id}", response_model=GitHubProjectOverviewResponse)
async def get_github_project_overview(
    repository_id: str = Path(pattern=r"^[0-9]{1,32}$"),
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> GitHubProjectOverviewResponse:
    """Read open issues and pull requests from one explicitly selected repository."""
    repository, token, path = await _selected_repository(authenticated.account.id, repository_id, db)
    issues, pulls = await asyncio.gather(
        _list_github_items(path, token, issues=True),
        _list_github_items(path, token, issues=False),
    )
    return GitHubProjectOverviewResponse(
        repository_id=repository_id,
        repository=repository.full_name,
        issues=[GitHubProjectIssue(**item) for item in issues],
        pull_requests=[GitHubProjectPullRequest(**item) for item in pulls],
    )


@router.get(
    "/github/agent/repositories/{repository_id}/pulls/{number}",
    response_model=GitHubPullDetailResponse,
)
async def get_github_pull_request_detail(
    repository_id: str = Path(pattern=r"^[0-9]{1,32}$"),
    number: int = Path(ge=1),
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> GitHubPullDetailResponse:
    """Read bounded pull request metadata, changed file patches, and check runs."""
    _, token, path = await _selected_repository(authenticated.account.id, repository_id, db)
    payload = await github_oauth_client.api_get_json(f"{path}/pulls/{number}", token)
    if not isinstance(payload, dict) or payload.get("number") != number:
        raise HTTPException(status_code=404, detail="Pull request was not found.")
    files_payload = await github_oauth_client.api_get_json(
        f"{path}/pulls/{number}/files", token, {"per_page": 100, "page": 1}
    )
    head = payload.get("head")
    if not isinstance(files_payload, list):
        raise GitHubIntegrationError("GitHub returned invalid pull request files.")
    files: list[GitHubPullFile] = []
    for item in files_payload[:20]:
        if not isinstance(item, dict) or not isinstance(item.get("filename"), str):
            continue
        files.append(
            GitHubPullFile(
                filename=item["filename"][:512],
                status=str(item.get("status", "modified"))[:32],
                additions=max(0, int(item.get("additions", 0))) if isinstance(item.get("additions", 0), int) else 0,
                deletions=max(0, int(item.get("deletions", 0))) if isinstance(item.get("deletions", 0), int) else 0,
                patch=item.get("patch", "")[:3_000] if isinstance(item.get("patch"), str) else None,
                html_url=item.get("html_url") if isinstance(item.get("html_url"), str) else None,
            )
        )
    head_sha = head.get("sha") if isinstance(head, dict) and isinstance(head.get("sha"), str) else None
    checks: list[GitHubCheckRun] = []
    checks_truncated = False
    if head_sha:
        check_payload = await github_oauth_client.api_get_json(
            f"{path}/commits/{quote(head_sha, safe='')}/check-runs", token, {"per_page": 100, "page": 1}
        )
        check_runs = check_payload.get("check_runs") if isinstance(check_payload, dict) else None
        if not isinstance(check_runs, list):
            raise GitHubIntegrationError("GitHub returned invalid check run data.")
        checks_truncated = len(check_runs) > 50
        for item in check_runs[:50]:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            checks.append(
                GitHubCheckRun(
                    name=item["name"][:200],
                    status=str(item.get("status", "unknown"))[:32],
                    conclusion=item.get("conclusion") if isinstance(item.get("conclusion"), str) else None,
                    html_url=item.get("html_url") if isinstance(item.get("html_url"), str) else None,
                )
            )
    return GitHubPullDetailResponse(
        repository_id=repository_id,
        number=number,
        title=str(payload.get("title", ""))[:300],
        body=payload.get("body")[:4_000] if isinstance(payload.get("body"), str) else "",
        state=str(payload.get("state", "open"))[:20],
        html_url=str(payload.get("html_url", "")),
        head_sha=head_sha,
        files=files,
        checks=checks,
        files_truncated=len(files_payload) > 20,
        checks_truncated=checks_truncated,
    )


@router.post(
    "/github/agent/repositories/{repository_id}/issues/{number}/proposals",
    response_model=GitHubIssueProposalResponse,
)
@limiter.limit(settings.rate_limit_llm)
async def propose_github_issue_actions(
    request: Request,
    repository_id: str = Path(pattern=r"^[0-9]{1,32}$"),
    number: int = Path(ge=1),
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> GitHubIssueProposalResponse:
    """Draft cited planner suggestions from one selected repository issue."""
    repository, token, path = await _selected_repository(authenticated.account.id, repository_id, db)
    issue = await github_oauth_client.api_get_json(f"{path}/issues/{number}", token)
    if not isinstance(issue, dict) or issue.get("number") != number or "pull_request" in issue:
        raise HTTPException(status_code=404, detail="Issue was not found.")
    title = issue.get("title")
    body = issue.get("body")
    if not isinstance(title, str):
        raise GitHubIntegrationError("GitHub returned an invalid issue.")
    source_text = f"Issue #{number}: {title}\n{body if isinstance(body, str) else ''}"[:24_000]
    if not source_text.strip():
        raise HTTPException(status_code=422, detail="This issue has no readable text.")
    from app.services.planner_agent import draft_action_items

    suggestions = await draft_action_items(source_text)
    return GitHubIssueProposalResponse(
        repository_id=repository_id,
        source_id=str(number),
        source_title=f"{repository.full_name} · #{number} {title[:180]}",
        suggestions=suggestions,
    )


@router.post(
    "/github/agent/repositories/{repository_id}/issues",
    response_model=GitHubIssueWriteResponse,
    status_code=201,
)
@limiter.limit(settings.rate_limit_default)
async def create_github_issue(
    body: GitHubIssueCreateRequest,
    request: Request,
    repository_id: str = Path(pattern=r"^[0-9]{1,32}$"),
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> GitHubIssueWriteResponse:
    """Create exactly the issue title and body submitted by the signed-in user."""
    _, token, path = await _selected_repository(authenticated.account.id, repository_id, db)
    payload = await github_oauth_client.api_post_json(
        f"{path}/issues", token, {"title": body.title, "body": body.body}
    )
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("number"), int)
        or not isinstance(payload.get("title"), str)
        or not isinstance(payload.get("html_url"), str)
    ):
        raise GitHubIntegrationError("GitHub returned an invalid issue response.")
    return GitHubIssueWriteResponse(
        number=payload["number"], title=payload["title"], html_url=payload["html_url"]
    )


@router.post(
    "/github/agent/repositories/{repository_id}/issues/{number}/comments",
    response_model=GitHubCommentWriteResponse,
    status_code=201,
)
@limiter.limit(settings.rate_limit_default)
async def create_github_issue_comment(
    body: GitHubCommentCreateRequest,
    request: Request,
    repository_id: str = Path(pattern=r"^[0-9]{1,32}$"),
    number: int = Path(ge=1),
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> GitHubCommentWriteResponse:
    """Post exactly the comment text submitted by the signed-in user."""
    _, token, path = await _selected_repository(authenticated.account.id, repository_id, db)
    payload = await github_oauth_client.api_post_json(
        f"{path}/issues/{number}/comments", token, {"body": body.body}
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("id"), int):
        raise GitHubIntegrationError("GitHub returned an invalid comment response.")
    html_url = payload.get("html_url")
    return GitHubCommentWriteResponse(
        id=str(payload["id"]), html_url=html_url if isinstance(html_url, str) else None
    )
