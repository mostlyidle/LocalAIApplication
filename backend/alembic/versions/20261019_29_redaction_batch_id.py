"""group redaction jobs into review batches

Revision ID: 20261019_29
Revises: 20261019_28
Create Date: 2026-10-19
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261019_29"
down_revision: str | None = "20261019_28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add an optional batch ID to each redaction job."""
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("redaction_jobs")}
    if "batch_id" not in columns:
        op.add_column("redaction_jobs", sa.Column("batch_id", sa.String(36), nullable=True))
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("redaction_jobs")}
    if "ix_redaction_jobs_batch_id" not in indexes:
        op.create_index("ix_redaction_jobs_batch_id", "redaction_jobs", ["batch_id"])


def downgrade() -> None:
    """Remove redaction batch grouping."""
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("redaction_jobs")}
    if "ix_redaction_jobs_batch_id" in indexes:
        op.drop_index("ix_redaction_jobs_batch_id", table_name="redaction_jobs")
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("redaction_jobs")}
    if "batch_id" in columns:
        op.drop_column("redaction_jobs", "batch_id")
