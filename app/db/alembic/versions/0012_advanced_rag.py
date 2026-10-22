"""Advanced RAG (ADR 0008): pgvector, chunk context/page/heading/embedding, document embedding and index version

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-22 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXED = "coalesce(context, '') || ' ' || text"
_NEW_TSV = f"to_tsvector('dutch'::regconfig, {_INDEXED}) || to_tsvector('simple'::regconfig, {_INDEXED})"
_OLD_TSV = "to_tsvector('dutch'::regconfig, text) || to_tsvector('simple'::regconfig, text)"


def _swap_tsv(expression: str) -> None:
    op.drop_index("ix_document_chunks_tsv", table_name="document_chunks", postgresql_using="gin")
    op.drop_column("document_chunks", "tsv")
    op.add_column(
        "document_chunks",
        sa.Column("tsv", postgresql.TSVECTOR(), sa.Computed(expression, persisted=True), nullable=False),
    )
    op.create_index("ix_document_chunks_tsv", "document_chunks", ["tsv"], unique=False, postgresql_using="gin")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("document_chunks", sa.Column("context", sa.Text(), nullable=True))
    op.add_column("document_chunks", sa.Column("page", sa.Integer(), nullable=True))
    op.add_column("document_chunks", sa.Column("heading", sa.String(length=200), nullable=True))
    op.add_column("document_chunks", sa.Column("embedding", Vector(1024), nullable=True))
    op.add_column("documents", sa.Column("index_version", sa.String(length=8), nullable=True))
    op.add_column("documents", sa.Column("doc_embedding", Vector(1024), nullable=True))
    _swap_tsv(_NEW_TSV)
    op.create_index(
        "ix_document_chunks_embedding", "document_chunks", ["embedding"], unique=False,
        postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"},
    )  # fmt: skip
    op.create_index(
        "ix_documents_doc_embedding", "documents", ["doc_embedding"], unique=False,
        postgresql_using="hnsw", postgresql_ops={"doc_embedding": "vector_cosine_ops"},
    )  # fmt: skip


def downgrade() -> None:
    op.drop_index("ix_documents_doc_embedding", table_name="documents", postgresql_using="hnsw")
    op.drop_index("ix_document_chunks_embedding", table_name="document_chunks", postgresql_using="hnsw")
    _swap_tsv(_OLD_TSV)
    op.drop_column("documents", "doc_embedding")
    op.drop_column("documents", "index_version")
    op.drop_column("document_chunks", "embedding")
    op.drop_column("document_chunks", "heading")
    op.drop_column("document_chunks", "page")
    op.drop_column("document_chunks", "context")
