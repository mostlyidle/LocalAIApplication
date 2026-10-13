"""persist account-selected GitHub repositories

Revision ID: 20261012_21
Revises: 20261012_20
Create Date: 2026-10-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261012_21"
down_revision: str | None = "20261012_20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the per-account repository allowlist."""
    op.create_table(
        "github_repository_selections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("repository_id", sa.String(length=32), nullable=False),
        sa.Column("full_name", sa.String(length=256), nullable=False),
        sa.Column("html_url", sa.String(length=512), nullable=False),
        sa.Column("default_branch", sa.String(length=256), nullable=False),
        sa.Column("is_private", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "repository_id"),
    )
    op.create_index(
        "ix_github_repository_selections_owner_id",
        "github_repository_selections",
        ["owner_id"],
    )


def downgrade() -> None:
    """Remove the per-account repository allowlist."""
    op.drop_index(
        "ix_github_repository_selections_owner_id", table_name="github_repository_selections"
    )
    op.drop_table("github_repository_selections")
