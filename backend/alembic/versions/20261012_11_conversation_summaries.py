"""add bounded conversation summaries

Revision ID: 20261012_11
Revises: 20261012_10
Create Date: 2026-10-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261012_11"
down_revision: str | None = "20261012_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store summary text and its ordered message boundary."""
    op.add_column("conversations", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column(
        "conversations",
        sa.Column("summary_through_message_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("summary_message_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "conversations",
        sa.Column("summary_revision", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    """Remove stored summary metadata."""
    op.drop_column("conversations", "summary_revision")
    op.drop_column("conversations", "summary_message_count")
    op.drop_column("conversations", "summary_through_message_id")
    op.drop_column("conversations", "summary")
