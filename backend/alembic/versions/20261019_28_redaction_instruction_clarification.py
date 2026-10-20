"""persist contextual redaction clarification state

Revision ID: 20261019_28
Revises: 20261019_27
Create Date: 2026-10-19
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261019_28"
down_revision: str | None = "20261019_27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the pending question and private clarification history to redaction jobs."""
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("redaction_jobs")}
    if "clarification_question" not in columns:
        op.add_column(
            "redaction_jobs", sa.Column("clarification_question", sa.Text(), nullable=True)
        )
    if "clarification_answers" not in columns:
        op.add_column(
            "redaction_jobs",
            sa.Column("clarification_answers", sa.Text(), nullable=False, server_default="[]"),
        )


def downgrade() -> None:
    """Remove redaction clarification state."""
    op.drop_column("redaction_jobs", "clarification_answers")
    op.drop_column("redaction_jobs", "clarification_question")
