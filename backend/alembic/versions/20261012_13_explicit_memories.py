"""add account-owned explicit memories

Revision ID: 20261012_13
Revises: 20261012_12
Create Date: 2026-10-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261012_13"
down_revision: str | None = "20261012_12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the SQL source of truth for explicitly saved memory."""
    op.create_table(
        "memories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("project_scope", sa.String(length=128), nullable=True),
        sa.Column("source_conversation_id", sa.String(length=36), nullable=True),
        sa.Column("source_message_id", sa.String(length=36), nullable=True),
        sa.Column("origin_agent", sa.String(length=64), nullable=True),
        sa.Column("approved", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memories_owner_id", "memories", ["owner_id"])
    op.create_index("ix_memories_owner_deleted", "memories", ["owner_id", "deleted_at"])
    op.create_index("ix_memories_owner_kind", "memories", ["owner_id", "kind"])


def downgrade() -> None:
    """Drop explicit memory records."""
    op.drop_index("ix_memories_owner_kind", table_name="memories")
    op.drop_index("ix_memories_owner_deleted", table_name="memories")
    op.drop_index("ix_memories_owner_id", table_name="memories")
    op.drop_table("memories")
