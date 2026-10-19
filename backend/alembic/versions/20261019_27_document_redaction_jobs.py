"""store account-owned document redaction job state

Revision ID: 20261019_27
Revises: 20261014_26
Create Date: 2026-10-19
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261019_27"
down_revision: str | None = "20261014_26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the redaction job state table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("redaction_jobs"):
        columns = {column["name"] for column in inspector.get_columns("redaction_jobs")}
        if "pages_processed" not in columns:
            op.add_column(
                "redaction_jobs",
                sa.Column("pages_processed", sa.Integer(), nullable=False, server_default="0"),
            )
        if "lease_until" not in columns:
            op.add_column("redaction_jobs", sa.Column("lease_until", sa.DateTime(), nullable=True))

        indexes = {index["name"] for index in inspector.get_indexes("redaction_jobs")}
        for name, index_columns in (
            ("ix_redaction_jobs_document_id", ["document_id"]),
            ("ix_redaction_jobs_owner_id", ["owner_id"]),
            ("ix_redaction_jobs_status", ["status"]),
            ("ix_redaction_jobs_status_created", ["status", "created_at"]),
        ):
            if name not in indexes:
                op.create_index(name, "redaction_jobs", index_columns)
        return

    op.create_table(
        "redaction_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("instructions", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("categories_json", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("job_dir", sa.String(length=1024), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("review_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("approved_revision", sa.Integer(), nullable=True),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_redaction_jobs_document_id", "redaction_jobs", ["document_id"])
    op.create_index("ix_redaction_jobs_owner_id", "redaction_jobs", ["owner_id"])
    op.create_index("ix_redaction_jobs_status", "redaction_jobs", ["status"])
    op.create_index("ix_redaction_jobs_status_created", "redaction_jobs", ["status", "created_at"])


def downgrade() -> None:
    """Drop redaction job state."""
    op.drop_index("ix_redaction_jobs_status_created", table_name="redaction_jobs")
    op.drop_index("ix_redaction_jobs_status", table_name="redaction_jobs")
    op.drop_index("ix_redaction_jobs_owner_id", table_name="redaction_jobs")
    op.drop_index("ix_redaction_jobs_document_id", table_name="redaction_jobs")
    op.drop_table("redaction_jobs")
