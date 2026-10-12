"""Operator-only account creation and password reset commands."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from getpass import getpass

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.models.db_models import (
    LEGACY_ACCOUNT_ID,
    Account,
    AccountSession,
    Conversation,
    Document,
    Meeting,
)
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


async def _assign_legacy_records(
    username: str,
    *,
    conversations: list[str] | None = None,
    documents: list[str] | None = None,
    meetings: list[str] | None = None,
    apply: bool = False,
) -> dict[str, dict[str, int]]:
    """Preview or explicitly assign selected quarantined records to an account."""
    selections = {
        "conversations": (Conversation, conversations or []),
        "documents": (Document, documents or []),
        "meetings": (Meeting, meetings or []),
    }
    if not any(ids for _, ids in selections.values()):
        raise ValueError("Select at least one conversation, document, or meeting ID.")

    factory = get_app_session_factory()
    async with factory() as session:
        account = await session.scalar(
            select(Account).where(Account.username == username, Account.is_enabled.is_(True))
        )
        if account is None:
            raise ValueError("Enabled account not found.")

        summary: dict[str, dict[str, int]] = {}
        updates = []
        for label, (model, ids) in selections.items():
            unique_ids = list(dict.fromkeys(ids))
            if not unique_ids:
                continue
            records = list(
                (await session.scalars(select(model).where(model.id.in_(unique_ids)))).all()
            )
            by_id = {record.id: record for record in records}
            if any(record_id not in by_id for record_id in unique_ids):
                raise ValueError(f"One or more selected {label} do not exist.")
            if any(
                by_id[record_id].owner_id not in {LEGACY_ACCOUNT_ID, account.id}
                for record_id in unique_ids
            ):
                raise ValueError(f"One or more selected {label} belong to another account.")

            pending = [
                by_id[record_id]
                for record_id in unique_ids
                if by_id[record_id].owner_id == LEGACY_ACCOUNT_ID
            ]
            summary[label] = {
                "selected": len(unique_ids),
                "to_assign": len(pending),
                "already_assigned": len(unique_ids) - len(pending),
            }
            updates.extend(pending)

        if apply:
            for record in updates:
                record.owner_id = account.id
            await session.commit()
        return summary


def main() -> None:
    """Run the account administration command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="create an account")
    create.add_argument("--username", required=True)
    create.add_argument("--display-name", required=True)
    reset = commands.add_parser("reset-password", help="reset an account password")
    reset.add_argument("username")
    assign = commands.add_parser(
        "assign-legacy", help="preview or assign explicitly selected quarantined records"
    )
    assign.add_argument("--username", required=True)
    assign.add_argument("--conversation", dest="conversations", action="append", default=[])
    assign.add_argument("--document", dest="documents", action="append", default=[])
    assign.add_argument("--meeting", dest="meetings", action="append", default=[])
    assign.add_argument("--apply", action="store_true", help="apply the assignment after review")
    args = parser.parse_args()

    try:
        if args.command == "assign-legacy":
            username = normalize_username(args.username)
            summary = asyncio.run(
                _assign_legacy_records(
                    username,
                    conversations=args.conversations,
                    documents=args.documents,
                    meetings=args.meetings,
                    apply=args.apply,
                )
            )
            for kind, counts in summary.items():
                print(
                    f"{kind}: selected={counts['selected']}, to_assign={counts['to_assign']}, "
                    f"already_assigned={counts['already_assigned']}"
                )
            print("Assignment applied." if args.apply else "Dry run only; pass --apply to assign.")
            return

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
