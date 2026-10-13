"""bind GitHub OAuth completion to its initiating browser

Revision ID: 20261012_23
Revises: 20261012_22
Create Date: 2026-10-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261012_23"
down_revision: str | None = "20261012_22"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "github_oauth_states",
        sa.Column("browser_binding_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("github_oauth_states", "browser_binding_hash")
