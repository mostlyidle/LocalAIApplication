"""persist selected profile results and artifacts on assistant messages

Revision ID: 20261012_04
Revises: 20260909_03
Create Date: 2026-10-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261012_04"
down_revision: str | None = "20260909_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable JSON-text execution metadata without changing existing history."""
    with op.batch_alter_table("messages") as batch_op:
        batch_op.add_column(sa.Column("execution_metadata", sa.Text(), nullable=True))
        batch_op.alter_column("agent_type", type_=sa.String(length=64), existing_type=sa.String(length=20))


def downgrade() -> None:
    """Remove profile execution metadata and restore the original agent field width."""
    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_column("execution_metadata")
        batch_op.alter_column("agent_type", type_=sa.String(length=20), existing_type=sa.String(length=64))
