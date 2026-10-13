"""Public status shapes for the per-user GitHub App connection."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic resolves response types at runtime.

from pydantic import BaseModel


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

