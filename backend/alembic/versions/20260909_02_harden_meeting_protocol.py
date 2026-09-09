"""harden meeting consent and lifecycle contract

Revision ID: 20260909_02
Revises: 20260909_01
Create Date: 2026-09-09

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260909_02"
down_revision: Union[str, None] = "20260909_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace boolean consent/sequence metadata with the canonical contract."""
    with op.batch_alter_table("meetings") as batch_op:
        batch_op.add_column(sa.Column("consent_policy_version", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("consent_attested_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("stopped_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("failed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("failure_reason", sa.Text(), nullable=True))

    op.execute(
        sa.text(
            "UPDATE meetings SET consent_policy_version = 'legacy-v1', "
            "consent_attested_at = created_at WHERE consent_policy_version IS NULL"
        )
    )
    with op.batch_alter_table("meetings") as batch_op:
        batch_op.alter_column("consent_policy_version", nullable=False)
        batch_op.alter_column("consent_attested_at", nullable=False)
        batch_op.alter_column("status", server_default="created")
        batch_op.alter_column("started_at", nullable=True)
        batch_op.drop_column("consent_given")
        batch_op.drop_column("last_audio_sequence")
        batch_op.drop_column("ended_at")

    with op.batch_alter_table("transcript_segments") as batch_op:
        batch_op.add_column(sa.Column("source", sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Restore the pre-hardening meeting columns for rollback."""
    with op.batch_alter_table("meetings") as batch_op:
        batch_op.add_column(sa.Column("consent_given", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("last_audio_sequence", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("ended_at", sa.DateTime(), nullable=True))

    op.execute(sa.text("UPDATE meetings SET consent_given = 1, last_audio_sequence = -1"))
    with op.batch_alter_table("meetings") as batch_op:
        batch_op.alter_column("consent_given", nullable=False)
        batch_op.alter_column("last_audio_sequence", nullable=False)
        batch_op.alter_column("status", server_default="active")
        batch_op.drop_column("failure_reason")
        batch_op.drop_column("failed_at")
        batch_op.drop_column("stopped_at")
        batch_op.drop_column("consent_attested_at")
        batch_op.drop_column("consent_policy_version")
    with op.batch_alter_table("transcript_segments") as batch_op:
        batch_op.drop_column("source")
