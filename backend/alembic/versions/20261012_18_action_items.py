"""add account-owned planner action items

Revision ID: 20261012_18
Revises: 20261012_17
Create Date: 2026-10-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261012_18"
down_revision: str | None = "20261012_17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the private action item table."""
    op.create_table(
        "action_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="next", nullable=False),
        sa.Column("priority", sa.String(length=16), server_default="normal", nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("source_type", sa.String(length=20), nullable=True),
        sa.Column("source_id", sa.String(length=36), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_action_items_owner_id", "action_items", ["owner_id"])
    op.create_index(
        "ix_action_items_owner_status_due", "action_items", ["owner_id", "status", "due_date"]
    )


def downgrade() -> None:
    """Drop action items."""
    op.drop_index("ix_action_items_owner_status_due", table_name="action_items")
    op.drop_index("ix_action_items_owner_id", table_name="action_items")
    op.drop_table("action_items")
