"""persist installation-wide agent prompt configuration

Revision ID: 20261013_25
Revises: 20261012_24
Create Date: 2026-10-13
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261013_25"
down_revision: str | None = "20261012_24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the application-wide agent configuration table."""
    op.create_table(
        "agent_configurations",
        sa.Column("name", sa.String(63), primary_key=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("target", sa.String(32), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("base_agent", sa.String(63), nullable=True),
        sa.Column("manifest_json", sa.Text(), nullable=True),
        sa.Column("is_custom", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("archived", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    """Drop the application-wide agent configuration table."""
    op.drop_table("agent_configurations")
