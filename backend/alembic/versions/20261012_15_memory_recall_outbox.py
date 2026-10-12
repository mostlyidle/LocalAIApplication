"""add durable jobs for eligible past-chat recall

Revision ID: 20261012_15
Revises: 20261012_14
Create Date: 2026-10-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261012_15"
down_revision: str | None = "20261012_14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist eligible chat turns for a recoverable indexing worker."""
    op.create_table(
        "memory_outbox_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("source_message_id", sa.String(length=36), nullable=False),
        sa.Column("memory_epoch", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_message_id", name="uq_memory_outbox_source_message"),
    )
    op.create_index("ix_memory_outbox_jobs_owner_id", "memory_outbox_jobs", ["owner_id"])
    op.create_index(
        "ix_memory_outbox_jobs_conversation_id", "memory_outbox_jobs", ["conversation_id"]
    )
    op.create_index(
        "ix_memory_outbox_jobs_status_available",
        "memory_outbox_jobs",
        ["status", "available_at"],
    )


def downgrade() -> None:
    """Remove the recall job table."""
    op.drop_index("ix_memory_outbox_jobs_status_available", table_name="memory_outbox_jobs")
    op.drop_index("ix_memory_outbox_jobs_conversation_id", table_name="memory_outbox_jobs")
    op.drop_index("ix_memory_outbox_jobs_owner_id", table_name="memory_outbox_jobs")
    op.drop_table("memory_outbox_jobs")
