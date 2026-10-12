"""Request and response schemas for account authentication."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    """Credentials for an operator-created account."""

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class AccountResponse(BaseModel):
    """Public account details, excluding credentials and internal flags."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    display_name: str


class LoginResponse(BaseModel):
    """Session bootstrap data returned after login or session refresh."""

    account: AccountResponse
    csrf_token: str
