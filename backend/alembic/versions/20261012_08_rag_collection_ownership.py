"""register account-owned RAG collections

Revision ID: 20261012_08
Revises: 20261012_07
Create Date: 2026-10-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261012_08"
down_revision: str | None = "20261012_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create ownership records; existing unregistered collections stay quarantined."""
    op.create_table(
        "rag_collections",
        sa.Column("name", sa.String(length=63), primary_key=True),
        sa.Column(
            "owner_id",
            sa.String(length=36),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_rag_collections_owner_id", "rag_collections", ["owner_id"])


def downgrade() -> None:
    """Remove account ownership records for vector collections."""
    op.drop_index("ix_rag_collections_owner_id", table_name="rag_collections")
    op.drop_table("rag_collections")
