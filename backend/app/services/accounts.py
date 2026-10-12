"""Account credential validation and password hashing."""

from __future__ import annotations

import re

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

_password_hash = PasswordHash.recommended()
_USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


def normalize_username(username: str) -> str:
    """Normalize and validate an operator-managed account name."""
    normalized = username.strip().casefold()
    if normalized == "legacy-import-disabled" or not _USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError("Username must be 3–64 letters, digits, dots, underscores, or hyphens.")
    return normalized


def hash_password(password: str) -> str:
    """Hash a password with the recommended Argon2 configuration."""
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters.")
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password while keeping malformed stored hashes non-fatal."""
    try:
        return _password_hash.verify(password, password_hash)
    except (TypeError, ValueError, UnknownHashError):
        return False
