"""add persistent resume rater workspaces, revisions and assessments

Revision ID: 20261020_30
Revises: 20261019_29
Create Date: 2026-10-20
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261020_30"
down_revision: str | None = "20261019_29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the private resume rating workflow tables."""
    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "resume_rater_workspaces" not in existing_tables:
        op.create_table(
            "resume_rater_workspaces",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "owner_id",
                sa.String(36),
                sa.ForeignKey("accounts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("current_revision", sa.Integer(), server_default="1", nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )

    if "resume_rater_revisions" not in existing_tables:
        op.create_table(
            "resume_rater_revisions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "workspace_id",
                sa.String(36),
                sa.ForeignKey("resume_rater_workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("job_posting", sa.Text(), nullable=False),
            sa.Column("criteria_json", sa.Text(), nullable=True),
            sa.Column("status", sa.String(24), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("workspace_id", "version", name="uq_resume_rater_revision_version"),
        )

    if "resume_rater_candidates" not in existing_tables:
        op.create_table(
            "resume_rater_candidates",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "workspace_id",
                sa.String(36),
                sa.ForeignKey("resume_rater_workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("display_name", sa.String(255), nullable=False),
            sa.Column("filename", sa.String(255), nullable=False),
            sa.Column("resume_path", sa.String(1024), nullable=False),
            sa.Column("content_sha256", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "workspace_id", "content_sha256", name="uq_resume_rater_candidate_file"
            ),
        )

    if "resume_rater_assessments" not in existing_tables:
        op.create_table(
            "resume_rater_assessments",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "workspace_id",
                sa.String(36),
                sa.ForeignKey("resume_rater_workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "candidate_id",
                sa.String(36),
                sa.ForeignKey("resume_rater_candidates.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "revision_id",
                sa.String(36),
                sa.ForeignKey("resume_rater_revisions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("status", sa.String(24), server_default="queued", nullable=False),
            sa.Column("score", sa.Integer(), nullable=True),
            sa.Column("result_json", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint(
                "candidate_id", "revision_id", name="uq_resume_rater_assessment_version"
            ),
        )

    if "resume_rater_tasks" not in existing_tables:
        op.create_table(
            "resume_rater_tasks",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "workspace_id",
                sa.String(36),
                sa.ForeignKey("resume_rater_workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "revision_id",
                sa.String(36),
                sa.ForeignKey("resume_rater_revisions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "assessment_id",
                sa.String(36),
                sa.ForeignKey("resume_rater_assessments.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("status", sa.String(16), server_default="queued", nullable=False),
            sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
            sa.Column("lease_until", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    indexes = (
        ("ix_resume_rater_workspaces_owner_id", "resume_rater_workspaces", ["owner_id"]),
        ("ix_resume_rater_revisions_workspace_id", "resume_rater_revisions", ["workspace_id"]),
        ("ix_resume_rater_revisions_status", "resume_rater_revisions", ["status"]),
        (
            "ix_resume_rater_revisions_workspace_status",
            "resume_rater_revisions",
            ["workspace_id", "status"],
        ),
        ("ix_resume_rater_candidates_workspace_id", "resume_rater_candidates", ["workspace_id"]),
        (
            "ix_resume_rater_candidates_workspace",
            "resume_rater_candidates",
            ["workspace_id", "created_at"],
        ),
        ("ix_resume_rater_assessments_workspace_id", "resume_rater_assessments", ["workspace_id"]),
        ("ix_resume_rater_assessments_candidate_id", "resume_rater_assessments", ["candidate_id"]),
        ("ix_resume_rater_assessments_revision_id", "resume_rater_assessments", ["revision_id"]),
        ("ix_resume_rater_assessments_status", "resume_rater_assessments", ["status"]),
        (
            "ix_resume_rater_assessments_revision_status",
            "resume_rater_assessments",
            ["revision_id", "status"],
        ),
        ("ix_resume_rater_tasks_workspace_id", "resume_rater_tasks", ["workspace_id"]),
        ("ix_resume_rater_tasks_revision_id", "resume_rater_tasks", ["revision_id"]),
        ("ix_resume_rater_tasks_status", "resume_rater_tasks", ["status"]),
        ("ix_resume_rater_tasks_status_created", "resume_rater_tasks", ["status", "created_at"]),
        ("ix_resume_rater_tasks_workspace", "resume_rater_tasks", ["workspace_id", "created_at"]),
    )
    for index_name, table_name, columns in indexes:
        existing_indexes = {
            item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table_name)
        }
        if index_name not in existing_indexes:
            op.create_index(index_name, table_name, columns)


def downgrade() -> None:
    """Remove resume rating workflow tables."""
    op.drop_table("resume_rater_tasks")
    op.drop_table("resume_rater_assessments")
    op.drop_table("resume_rater_candidates")
    op.drop_table("resume_rater_revisions")
    op.drop_table("resume_rater_workspaces")
