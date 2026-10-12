"""store stable per-session CSRF tokens

Revision ID: 20261012_07
Revises: 20261012_06
Create Date: 2026-10-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261012_07"
down_revision: str | None = "20261012_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace CSRF digests and revoke sessions needing a fresh login."""
    with op.batch_alter_table("account_sessions") as batch_op:
        batch_op.add_column(sa.Column("csrf_token", sa.String(length=64), nullable=True))
    op.execute(
        sa.text(
            "UPDATE account_sessions SET csrf_token = '!reauthentication-required!', "
            "revoked_at = CURRENT_TIMESTAMP WHERE csrf_token IS NULL"
        )
    )
    with op.batch_alter_table("account_sessions") as batch_op:
        batch_op.alter_column("csrf_token", nullable=False)
        batch_op.drop_column("csrf_token_hash")


def downgrade() -> None:
    """Restore the digest column; existing sessions remain revoked."""
    with op.batch_alter_table("account_sessions") as batch_op:
        batch_op.add_column(sa.Column("csrf_token_hash", sa.String(length=64), nullable=True))
    op.execute(
        sa.text(
            "UPDATE account_sessions SET csrf_token_hash = '!reauthentication-required!', "
            "revoked_at = CURRENT_TIMESTAMP WHERE csrf_token_hash IS NULL"
        )
    )
    with op.batch_alter_table("account_sessions") as batch_op:
        batch_op.alter_column("csrf_token_hash", nullable=False)
        batch_op.drop_column("csrf_token")
