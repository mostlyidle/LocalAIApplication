"""Per-account GitHub App authorization endpoints."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select

from app.config import settings
from app.dependencies import get_authenticated_session, get_db
from app.models.db_models import GitHubConnection, GitHubOAuthState, GitHubRepositorySelection
from app.models.github_schemas import (
    GitHubAuthorizationResponse,
    GitHubConnectionResponse,
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
