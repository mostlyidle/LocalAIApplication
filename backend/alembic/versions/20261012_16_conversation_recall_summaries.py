"""store bounded SQL summaries for opted-in past-chat recall

Revision ID: 20261012_16
Revises: 20261012_15
Create Date: 2026-10-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261012_16"
down_revision: str | None = "20261012_15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add one derived summary row per source conversation."""
    op.create_table(
        "conversation_recall_summaries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("source_message_id", sa.String(length=36), nullable=False),
        sa.Column("memory_epoch", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", name="uq_recall_summary_conversation"),
    )
    op.create_index(
        "ix_conversation_recall_summaries_owner_id", "conversation_recall_summaries", ["owner_id"]
    )
    op.create_index(
        "ix_recall_summaries_owner_epoch",
        "conversation_recall_summaries",
        ["owner_id", "memory_epoch"],
    )


def downgrade() -> None:
    """Remove derived recall summaries."""
    op.drop_index("ix_recall_summaries_owner_epoch", table_name="conversation_recall_summaries")
    op.drop_index(
        "ix_conversation_recall_summaries_owner_id", table_name="conversation_recall_summaries"
    )
    op.drop_table("conversation_recall_summaries")
