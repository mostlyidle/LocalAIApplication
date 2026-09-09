"""persist meeting transcript sequence allocation

Revision ID: 20260909_03
Revises: 20260909_02
Create Date: 2026-09-09

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260909_03"
down_revision: str | None = "20260909_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the durable counter used to allocate transcript sequences atomically."""
    with op.batch_alter_table("meetings") as batch_op:
        batch_op.add_column(
            sa.Column("next_transcript_sequence", sa.Integer(), nullable=True, server_default="0")
        )
    op.execute(
        sa.text(
            "UPDATE meetings "
            "SET next_transcript_sequence = COALESCE("
            "(SELECT MAX(transcript_segments.sequence) + 1 "
            "FROM transcript_segments "
            "WHERE transcript_segments.meeting_id = meetings.id), 0)"
        )
    )
    with op.batch_alter_table("meetings") as batch_op:
        batch_op.alter_column("next_transcript_sequence", nullable=False, server_default="0")


def downgrade() -> None:
    """Remove the durable transcript sequence counter."""
    with op.batch_alter_table("meetings") as batch_op:
        batch_op.drop_column("next_transcript_sequence")
