"""link planner items to their source GitHub repository

Revision ID: 20261012_22
Revises: 20261012_21
Create Date: 2026-10-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261012_22"
down_revision: str | None = "20261012_21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store the repository ID needed to revalidate GitHub planner citations."""
    op.add_column("action_items", sa.Column("source_repository_id", sa.String(length=32), nullable=True))


def downgrade() -> None:
    """Remove GitHub source repository identifiers."""
    op.drop_column("action_items", "source_repository_id")
