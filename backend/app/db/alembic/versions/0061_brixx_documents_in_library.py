"""brixx documents in library: a document comes from a mail attachment or from BRIXX

Revision ID: 0061
Revises: 0060
Create Date: 2026-11-27 10:00:00

BRIXX documents (leases, contracts, the tenant's papers) were downloaded but never read. They now become library
documents like filed attachments, so dossiers and Astra find them through the same links and search. A document has
exactly one source: `attachment_id` (now nullable) or `brixx_document_id`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0061"
down_revision: str | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("brixx_document_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_documents_brixx_document_id_brixx_documents"), "documents", "brixx_documents",
        ["brixx_document_id"], ["id"],
    )  # fmt: skip
    op.create_unique_constraint(op.f("uq_documents_brixx_document_id"), "documents", ["brixx_document_id"])
    op.alter_column("documents", "attachment_id", existing_type=sa.Uuid(), nullable=True)
    op.create_check_constraint(
        op.f("ck_documents_one_source"), "documents", "(attachment_id IS NULL) <> (brixx_document_id IS NULL)"
    )


def downgrade() -> None:
    op.execute("DELETE FROM documents WHERE attachment_id IS NULL")  # chunks and links cascade
    op.drop_constraint(op.f("ck_documents_one_source"), "documents", type_="check")
    op.alter_column("documents", "attachment_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_constraint(op.f("uq_documents_brixx_document_id"), "documents", type_="unique")
    op.drop_constraint(op.f("fk_documents_brixx_document_id_brixx_documents"), "documents", type_="foreignkey")
    op.drop_column("documents", "brixx_document_id")
