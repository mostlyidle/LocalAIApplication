"""Operator-only account creation and password reset commands."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from getpass import getpass

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.models.db_models import Account, AccountSession
from app.services.accounts import hash_password, normalize_username
from app.services.database import close_app_db, get_app_session_factory


async def _create_account(username: str, display_name: str, password: str) -> None:
    """Create one account after the database migrations have been applied."""
    factory = get_app_session_factory()
    async with factory() as session:
        if await session.scalar(select(Account.id).where(Account.username == username)):
            raise ValueError("An account with that username already exists.")
        session.add(
            Account(
                username=username,
                display_name=display_name.strip(),
                password_hash=hash_password(password),
            )
        )
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ValueError("An account with that username already exists.") from exc


async def _reset_password(username: str, password: str) -> None:
    """Reset an account password and revoke its existing sessions."""
    factory = get_app_session_factory()
    async with factory() as session:
        account = await session.scalar(select(Account).where(Account.username == username))
        if account is None:
            raise ValueError("Account not found.")
        account.password_hash = hash_password(password)
        await session.execute(
            update(AccountSession)
            .where(AccountSession.account_id == account.id, AccountSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await session.commit()


def main() -> None:
    """Run the account administration command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="create an account")
    create.add_argument("--username", required=True)
    create.add_argument("--display-name", required=True)
    reset = commands.add_parser("reset-password", help="reset an account password")
    reset.add_argument("username")
    args = parser.parse_args()

    try:
        username = normalize_username(args.username)
        if args.command == "create" and not args.display_name.strip():
            raise ValueError("Display name cannot be empty.")
        password = getpass("New password: ")
        if password != getpass("Confirm password: "):
            raise ValueError("Passwords do not match.")
        if args.command == "create":
            asyncio.run(_create_account(username, args.display_name, password))
            print(f"Created account {username}.")
        else:
            asyncio.run(_reset_password(username, password))
            print(f"Reset password for {username}; existing sessions were revoked.")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"error: {exc}\n")
    finally:
        asyncio.run(close_app_db())


if __name__ == "__main__":
    main()
