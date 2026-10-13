"""store verbatim evidence for reviewed planner tasks

Revision ID: 20261012_19
Revises: 20261012_18
Create Date: 2026-10-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op
import sqlalchemy as sa

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261012_19"
down_revision: str | None = "20261012_18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store a source quote on each task accepted from a suggestion."""
    op.add_column("action_items", sa.Column("source_quote", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove stored action item source quotes."""
    op.drop_column("action_items", "source_quote")
