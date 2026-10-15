"""store document content fingerprints for duplicate grouping

Revision ID: 20261014_26
Revises: 20261013_25
Create Date: 2026-10-14
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261014_26"
down_revision: str | None = "20261013_25"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add a nullable SHA-256 fingerprint for existing and new uploads."""
    op.add_column("documents", sa.Column("content_sha256", sa.String(64), nullable=True))


def downgrade() -> None:
    """Remove document content fingerprints."""
    op.drop_column("documents", "content_sha256")
