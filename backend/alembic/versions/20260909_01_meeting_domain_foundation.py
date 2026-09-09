"""meeting domain foundation

Revision ID: 20260909_01
Revises: 7594d38c6848
Create Date: 2026-09-09

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260909_01"
down_revision: Union[str, None] = "7594d38c6848"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create consented meeting metadata and Phase 2 transcript entities."""
    op.create_table(
        "meetings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("consent_given", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_audio_sequence", sa.Integer(), nullable=False, server_default="-1"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_meetings_status"), "meetings", ["status"], unique=False)

    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("meeting_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("speaker", sa.String(length=100), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=True),
        sa.Column("end_ms", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id", "sequence", name="uq_transcript_meeting_sequence"),
    )
    op.create_index(
        op.f("ix_transcript_segments_meeting_id"),
        "transcript_segments",
        ["meeting_id"],
        unique=False,
    )

    op.create_table(
        "detected_questions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("meeting_id", sa.String(length=36), nullable=False),
        sa.Column("transcript_segment_id", sa.String(length=36), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["transcript_segment_id"], ["transcript_segments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_detected_questions_meeting_id"),
        "detected_questions",
        ["meeting_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_detected_questions_transcript_segment_id"),
        "detected_questions",
        ["transcript_segment_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop meeting domain tables in dependency order."""
    op.drop_index(op.f("ix_detected_questions_transcript_segment_id"), table_name="detected_questions")
    op.drop_index(op.f("ix_detected_questions_meeting_id"), table_name="detected_questions")
    op.drop_table("detected_questions")
    op.drop_index(op.f("ix_transcript_segments_meeting_id"), table_name="transcript_segments")
    op.drop_table("transcript_segments")
    op.drop_index(op.f("ix_meetings_status"), table_name="meetings")
    op.drop_table("meetings")
