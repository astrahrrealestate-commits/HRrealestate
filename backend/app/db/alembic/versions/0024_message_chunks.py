"""message_chunks and message_index_state for Message RAG

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-31 18:35:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXED = "coalesce(context, '') || ' ' || text"
_TSV = f"to_tsvector('dutch'::regconfig, {_INDEXED}) || to_tsvector('simple'::regconfig, {_INDEXED})"


def upgrade() -> None:
    # 1. message_chunks table
    op.create_table(
        "message_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("thread_ref", sa.String(length=255), nullable=False),
        sa.Column("message_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False),
        sa.Column("first_message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("last_message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("people.id", ondelete="SET NULL"), nullable=True),
        sa.Column("participant_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), server_default="{}", nullable=False),
        sa.Column("unit_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("units.id", ondelete="SET NULL"), nullable=True),
        sa.Column("lease_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("leases.id", ondelete="SET NULL"), nullable=True),
        sa.Column("case_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), server_default="{}", nullable=False),
        sa.Column("has_inbound", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("has_outbound", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("first_sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("categories", postgresql.ARRAY(sa.String(length=32)), server_default="{}", nullable=False),
        sa.Column("max_urgency", sa.String(length=32), nullable=True),
        sa.Column("attachment_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), server_default="{}", nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("tsv", postgresql.TSVECTOR(), sa.Computed(_TSV, persisted=True), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("embed_model", sa.String(length=64), nullable=True),
        sa.Column("embed_dim", sa.Integer(), server_default="1024", nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("is_open", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # 2. Indexes for message_chunks
    op.create_index(
        "uq_message_chunks_thread_first_msg",
        "message_chunks",
        ["company_id", "channel", "first_message_id"],
        unique=True,
    )
    op.create_index(
        "ix_message_chunks_tsv",
        "message_chunks",
        ["tsv"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "ix_message_chunks_embedding",
        "message_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_message_chunks_case_ids",
        "message_chunks",
        ["case_ids"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "ix_message_chunks_participant_ids",
        "message_chunks",
        ["participant_ids"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "ix_message_chunks_person_timeline",
        "message_chunks",
        ["company_id", "person_id", sa.text("last_sent_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_message_chunks_unit_timeline",
        "message_chunks",
        ["company_id", "unit_id", sa.text("last_sent_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_message_chunks_company_sent",
        "message_chunks",
        ["company_id", sa.text("last_sent_at DESC")],
        unique=False,
    )

    # 3. message_index_state table
    op.create_table(
        "message_index_state",
        sa.Column("message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=100), nullable=True),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("message_chunks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'indexed', 'skipped', 'failed')",
            name="ck_message_index_state_status",
        ),
    )
    op.create_index(
        "ix_message_index_state_status",
        "message_index_state",
        ["status", "updated_at"],
        unique=False,
    )

    # 4. Grant read-only access to estateos_readonly role if present
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'estateos_readonly') THEN
                GRANT SELECT ON message_chunks, message_index_state TO estateos_readonly;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_table("message_index_state")
    op.drop_table("message_chunks")
