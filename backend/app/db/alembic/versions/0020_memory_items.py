"""memory_items: T5 standing preferences, owner rules, and distilled memory

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-23 17:30:00

Creates the `memory_items` table with vector embeddings for semantic retrieval (spec §6.2, Task C11).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

from app.core.settings import EMBEDDING_DIMENSIONS

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "memory_items"


_FEED_KINDS_BEFORE = "'approval', 'document_review', 'alert', 'briefing', 'task', 'agent_note'"
_FEED_KINDS_NOW = "'approval', 'document_review', 'memory_review', 'alert', 'briefing', 'task', 'agent_note'"


def _swap_feed_kind_check(allowed: str) -> None:
    """`owner_feed.kind` gains `memory_review` (the owner reviews proposed memory items in the dashboard feed)."""
    op.drop_constraint(op.f("ck_owner_feed_kind"), "owner_feed", type_="check")
    op.create_check_constraint(op.f("ck_owner_feed_kind"), "owner_feed", f"kind IN ({allowed})")


def upgrade() -> None:
    _swap_feed_kind_check(_FEED_KINDS_NOW)
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("text", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="proposed", nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("source_refs", JSONB(), server_default="[]", nullable=False),
        sa.Column("evidence_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("confidence", sa.Float(), server_default="1.0", nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_memory_items_company_id_companies"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_items")),
    )
    for column, values in (
        ("scope", ("company", "owner", "person", "unit", "case")),
        ("kind", ("rule", "preference", "fact", "note")),
        ("status", ("proposed", "active", "retired")),
        ("origin", ("owner", "distilled", "system")),
    ):  # the CHECKs a str_enum column gets from its model
        allowed = ", ".join(f"'{v}'" for v in values)
        op.create_check_constraint(op.f(f"ck_memory_items_{column}"), TABLE, f"{column} IN ({allowed})")
    op.create_index(
        "ix_memory_items_company_status", TABLE, ["company_id", "status"], unique=False
    )
    op.create_index(
        "ix_memory_items_scope_lookup", TABLE, ["company_id", "scope", "scope_id"], unique=False
    )
    op.create_index(
        "ix_memory_items_scope_id", TABLE, ["scope_id"], unique=False
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_memory_items_active
        ON memory_items (company_id, scope, scope_id, lower(text))
        WHERE status <> 'retired'
        """
    )
    op.execute(
        """
        CREATE INDEX ix_memory_items_embedding
        ON memory_items USING hnsw (embedding vector_cosine_ops)
        """
    )


def downgrade() -> None:
    op.drop_index("ix_memory_items_embedding", table_name=TABLE)
    op.drop_index("uq_memory_items_active", table_name=TABLE)
    op.drop_index("ix_memory_items_scope_id", table_name=TABLE)
    op.drop_index("ix_memory_items_scope_lookup", table_name=TABLE)
    op.drop_index("ix_memory_items_company_status", table_name=TABLE)
    op.execute("DELETE FROM owner_feed WHERE kind = 'memory_review'")  # the older constraint cannot hold them
    _swap_feed_kind_check(_FEED_KINDS_BEFORE)
    op.drop_table(TABLE)
