"""store the digest used to validate session-bound CSRF tokens

Revision ID: 20261012_06
Revises: 20261012_05
Create Date: 2026-10-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261012_06"
down_revision: str | None = "20261012_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the CSRF digest, invalidating old sessions that lack one."""
    with op.batch_alter_table("account_sessions") as batch_op:
        batch_op.add_column(sa.Column("csrf_token_hash", sa.String(length=64), nullable=True))
    op.execute(
        sa.text(
            "UPDATE account_sessions SET csrf_token_hash = "
            "'!reauthentication-required!' WHERE csrf_token_hash IS NULL"
        )
    )
    with op.batch_alter_table("account_sessions") as batch_op:
        batch_op.alter_column("csrf_token_hash", nullable=False)


def downgrade() -> None:
    """Remove the stored CSRF digest."""
    with op.batch_alter_table("account_sessions") as batch_op:
        batch_op.drop_column("csrf_token_hash")
