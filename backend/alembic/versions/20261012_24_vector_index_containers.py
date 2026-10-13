"""add account-owned vector index containers and file state

Revision ID: 20261012_24
Revises: 20261012_23
Create Date: 2026-10-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261012_24"
down_revision: str | None = "20261012_23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("rag_collections", sa.Column("display_name", sa.String(120), nullable=True))
    op.create_index(
        "uq_rag_collections_owner_display_name",
        "rag_collections",
        ["owner_id", "display_name"],
        unique=True,
    )
    op.create_table(
        "rag_container_files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "collection_name",
            sa.String(63),
            sa.ForeignKey("rag_collections.name", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("indexed_document_id", sa.String(36), nullable=True),
        sa.Column("relative_path", sa.String(1024), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), server_default="staged", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "collection_name", "relative_path", name="uq_rag_container_file_path"
        ),
    )
    op.create_index(
        "ix_rag_container_files_collection_name",
        "rag_container_files",
        ["collection_name"],
    )
    op.create_index(
        "ix_rag_container_files_document_id", "rag_container_files", ["document_id"]
    )
    op.create_index(
        "ix_rag_container_files_status_available",
        "rag_container_files",
        ["status", "available_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_rag_container_files_status_available", table_name="rag_container_files")
    op.drop_index("ix_rag_container_files_document_id", table_name="rag_container_files")
    op.drop_index("ix_rag_container_files_collection_name", table_name="rag_container_files")
    op.drop_table("rag_container_files")
    op.drop_index("uq_rag_collections_owner_display_name", table_name="rag_collections")
    op.drop_column("rag_collections", "display_name")
