"""add client turn identifiers to chat messages

Revision ID: 20261012_12
Revises: 20261012_11
Create Date: 2026-10-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261012_12"
down_revision: str | None = "20261012_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store a client turn key and prevent duplicate user/assistant rows."""
    op.add_column("messages", sa.Column("client_turn_id", sa.String(length=36), nullable=True))
    op.add_column("messages", sa.Column("turn_status", sa.String(length=16), nullable=True))
    op.create_index(
        "uq_messages_conversation_client_turn_role",
        "messages",
        ["conversation_id", "client_turn_id", "role"],
        unique=True,
    )


def downgrade() -> None:
    """Drop client turn keys."""
    op.drop_index("uq_messages_conversation_client_turn_role", table_name="messages")
    op.drop_column("messages", "turn_status")
    op.drop_column("messages", "client_turn_id")
