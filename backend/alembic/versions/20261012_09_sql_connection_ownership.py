"""register account-owned SQL connections

Revision ID: 20261012_09
Revises: 20261012_08
Create Date: 2026-10-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261012_09"
down_revision: str | None = "20261012_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create account ownership records; pre-existing named engines stay quarantined."""
    op.create_table(
        "sql_connections",
        sa.Column("name", sa.String(length=100), primary_key=True),
        sa.Column(
            "owner_id",
            sa.String(length=36),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sql_connections_owner_id", "sql_connections", ["owner_id"])


def downgrade() -> None:
    """Remove registered SQL connection ownership."""
    op.drop_index("ix_sql_connections_owner_id", table_name="sql_connections")
    op.drop_table("sql_connections")
