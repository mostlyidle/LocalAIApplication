"""queue durable deletion of derived past-chat vectors

Revision ID: 20261012_17
Revises: 20261012_16
Create Date: 2026-10-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261012_17"
down_revision: str | None = "20261012_16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Keep vector deletion durable after the source SQL rows are removed."""
    op.create_table(
        "memory_vector_cleanup_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_vector_cleanup_jobs_owner_id", "memory_vector_cleanup_jobs", ["owner_id"]
    )
    op.create_index(
        "ix_memory_cleanup_status_available",
        "memory_vector_cleanup_jobs",
        ["status", "available_at"],
    )


def downgrade() -> None:
    """Remove vector cleanup jobs."""
    op.drop_index("ix_memory_cleanup_status_available", table_name="memory_vector_cleanup_jobs")
    op.drop_index("ix_memory_vector_cleanup_jobs_owner_id", table_name="memory_vector_cleanup_jobs")
    op.drop_table("memory_vector_cleanup_jobs")
