"""add encrypted per-account GitHub App connections

Revision ID: 20261012_20
Revises: 20261012_19
Create Date: 2026-10-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261012_20"
down_revision: str | None = "20261012_19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create credential and one-time OAuth state tables."""
    op.create_table(
        "github_connections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("github_user_id", sa.String(length=32), nullable=False),
        sa.Column("github_login", sa.String(length=128), nullable=False),
        sa.Column("encrypted_access_token", sa.Text(), nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("refresh_expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id"),
    )
    op.create_index("ix_github_connections_owner_id", "github_connections", ["owner_id"])
    op.create_table(
        "github_oauth_states",
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["account_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("state_hash"),
    )
    op.create_index("ix_github_oauth_states_owner_id", "github_oauth_states", ["owner_id"])
    op.create_index("ix_github_oauth_states_session_id", "github_oauth_states", ["session_id"])
    op.create_index("ix_github_oauth_states_expires_at", "github_oauth_states", ["expires_at"])


def downgrade() -> None:
    """Remove OAuth state and GitHub connection tables."""
    op.drop_index("ix_github_oauth_states_expires_at", table_name="github_oauth_states")
    op.drop_index("ix_github_oauth_states_session_id", table_name="github_oauth_states")
    op.drop_index("ix_github_oauth_states_owner_id", table_name="github_oauth_states")
    op.drop_table("github_oauth_states")
    op.drop_index("ix_github_connections_owner_id", table_name="github_connections")
    op.drop_table("github_connections")
