"""add session-bound native meeting stream tickets

Revision ID: 20261012_10
Revises: 20261012_09
Create Date: 2026-10-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261012_10"
down_revision: str | None = "20261012_09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store only hashes of meeting tickets and bind them to live sessions."""
    op.create_table(
        "meeting_stream_tickets",
        sa.Column("token_hash", sa.String(length=64), primary_key=True),
        sa.Column(
            "meeting_id",
            sa.String(length=36),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.String(length=36),
            sa.ForeignKey("account_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_meeting_stream_tickets_meeting_id", "meeting_stream_tickets", ["meeting_id"]
    )
    op.create_index(
        "ix_meeting_stream_tickets_session_id", "meeting_stream_tickets", ["session_id"]
    )
    op.create_index(
        "ix_meeting_stream_tickets_expires_at", "meeting_stream_tickets", ["expires_at"]
    )


def downgrade() -> None:
    """Drop native meeting stream tickets."""
    op.drop_index("ix_meeting_stream_tickets_expires_at", table_name="meeting_stream_tickets")
    op.drop_index("ix_meeting_stream_tickets_session_id", table_name="meeting_stream_tickets")
    op.drop_index("ix_meeting_stream_tickets_meeting_id", table_name="meeting_stream_tickets")
    op.drop_table("meeting_stream_tickets")
