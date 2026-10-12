"""Operator-created account login and server-side browser sessions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from app.api.middleware.rate_limiting import limiter
from app.config import settings
from app.dependencies import get_authenticated_session, get_db
from app.models.auth_schemas import AccountResponse, LoginRequest, LoginResponse
from app.models.db_models import Account
from app.services.accounts import dummy_password_hash, normalize_username, verify_password
from app.services.auth import (
    SESSION_COOKIE,
    AuthenticatedSession,
    create_session,
    revoke_session,
    rotate_csrf_token,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> LoginResponse:
    """Verify operator-created credentials and issue a private session cookie."""
    try:
        username = normalize_username(body.username)
    except ValueError:
        username = ""
    account = (
        await db.scalar(select(Account).where(Account.username == username)) if username else None
    )
    password_hash = account.password_hash if account is not None else dummy_password_hash()
    valid_password = verify_password(body.password, password_hash)
    if account is None or not account.is_enabled or not valid_password:
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    session, token, csrf_token = await create_session(db, account)
    max_age = settings.auth_session_ttl_hours * 60 * 60
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="strict",
        path="/api/v1",
    )
    return LoginResponse(account=AccountResponse.model_validate(account), csrf_token=csrf_token)


@router.get("/me", response_model=LoginResponse)
async def current_account(
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> LoginResponse:
    """Return the signed-in account and refresh its one-time CSRF token."""
    csrf_token = await rotate_csrf_token(db, authenticated.session)
    return LoginResponse(
        account=AccountResponse.model_validate(authenticated.account),
        csrf_token=csrf_token,
    )


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> Response:
    """Revoke the current session and remove its browser cookie."""
    await revoke_session(db, authenticated.session)
    response.delete_cookie(
        SESSION_COOKIE,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="strict",
        path="/api/v1",
    )
    response.status_code = 204
    return response
