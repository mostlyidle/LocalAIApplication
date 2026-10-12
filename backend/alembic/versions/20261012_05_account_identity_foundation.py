"""add account identities and quarantine pre-account records

Revision ID: 20261012_05
Revises: 20261012_04
Create Date: 2026-10-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261012_05"
down_revision: str | None = "20261012_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_ACCOUNT_ID = "00000000-0000-4000-8000-000000000000"


def upgrade() -> None:
    """Create disabled legacy ownership and assign existing data to it."""
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("memory_enabled", sa.Boolean(), nullable=False),
        sa.Column("past_chat_recall_enabled", sa.Boolean(), nullable=False),
        sa.Column("memory_epoch", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_accounts_username", "accounts", ["username"], unique=True)
    op.create_table(
        "account_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_account_sessions_account_id", "account_sessions", ["account_id"])
    op.create_index("ix_account_sessions_expires_at", "account_sessions", ["expires_at"])
    op.create_index(
        "ix_account_sessions_token_hash", "account_sessions", ["token_hash"], unique=True
    )

    now = sa.text("CURRENT_TIMESTAMP")
    op.execute(
        sa.text(
            "INSERT INTO accounts (id, username, display_name, password_hash, is_enabled, "
            "memory_enabled, past_chat_recall_enabled, memory_epoch, created_at, updated_at) "
            "VALUES (:id, :username, :display_name, :password_hash, 0, 0, 0, 0, "
            f"{now}, {now})"
        ).bindparams(
            id=LEGACY_ACCOUNT_ID,
            username="legacy-import-disabled",
            display_name="Unassigned legacy data",
            password_hash="!disabled!",
        )
    )

    for table_name in ("conversations", "documents", "meetings"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(sa.Column("owner_id", sa.String(length=36), nullable=True))
        op.execute(
            sa.text(
                f"UPDATE {table_name} SET owner_id = :owner_id WHERE owner_id IS NULL"
            ).bindparams(owner_id=LEGACY_ACCOUNT_ID)
        )
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column("owner_id", nullable=False)
            batch_op.create_foreign_key(
                f"fk_{table_name}_owner_id_accounts",
                "accounts",
                ["owner_id"],
                ["id"],
                ondelete="RESTRICT",
            )
            batch_op.create_index(f"ix_{table_name}_owner_id", ["owner_id"])


def downgrade() -> None:
    """Remove identity tables and ownership after the operator has handled data."""
    for table_name in ("meetings", "documents", "conversations"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_index(f"ix_{table_name}_owner_id")
            batch_op.drop_constraint(f"fk_{table_name}_owner_id_accounts", type_="foreignkey")
            batch_op.drop_column("owner_id")
    op.drop_index("ix_account_sessions_token_hash", table_name="account_sessions")
    op.drop_index("ix_account_sessions_expires_at", table_name="account_sessions")
    op.drop_index("ix_account_sessions_account_id", table_name="account_sessions")
    op.drop_table("account_sessions")
    op.drop_index("ix_accounts_username", table_name="accounts")
    op.drop_table("accounts")
