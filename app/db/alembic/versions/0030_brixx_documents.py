"""brixx_documents: one row per downloaded (or attempted) version of a BRIXX document file

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-03 10:00:00

Content is unique per (company_id, document_id, sha256); the claim of a version per (company_id, document_id,
source_version). sha256 is NULL until the bytes are stored, and NULLs stay distinct, so unfinished versions coexist.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "brixx_documents"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("source_version", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(length=128), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_brixx_documents_company_id_companies"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_brixx_documents")),
        sa.UniqueConstraint(
            "company_id", "document_id", "sha256", name=op.f("uq_brixx_documents_company_id_document_id_sha256")
        ),
        sa.UniqueConstraint(
            "company_id",
            "document_id",
            "source_version",
            name=op.f("uq_brixx_documents_company_id_document_id_source_version"),
        ),
    )
    op.create_check_constraint(
        op.f("ck_brixx_documents_status"), TABLE, "status IN ('pending', 'stored', 'forbidden', 'failed')"
    )


def downgrade() -> None:
    op.drop_table(TABLE)
