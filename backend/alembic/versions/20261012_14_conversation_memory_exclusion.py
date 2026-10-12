"""allow conversations to opt out of cross-chat memory

Revision ID: 20261012_14
Revises: 20261012_13
Create Date: 2026-10-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261012_14"
down_revision: str | None = "20261012_13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Default existing conversations to eligible unless excluded by their owner."""
    op.add_column(
        "conversations",
        sa.Column("exclude_from_memory", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    """Remove the conversation recall exclusion setting."""
    op.drop_column("conversations", "exclude_from_memory")
