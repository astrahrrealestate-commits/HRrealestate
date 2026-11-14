"""translations: cached Dutch to English translations keyed by source text hash

Revision ID: 0038
Revises: 0037
Create Date: 2026-11-10 13:00:00

One row per distinct text and company (unique company_id + source_hash), so a message, a draft or a repeated
quote is translated by the local model once. The source text itself is not stored; the English copy is erased with
the person's messages (GDPR).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "translations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("source_lang", sa.String(length=8), nullable=False),
        sa.Column("text_en", sa.Text(), nullable=False),
        sa.Column("engine", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_translations_company_id_companies"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_translations")),
        sa.UniqueConstraint("company_id", "source_hash", name=op.f("uq_translations_company_id_source_hash")),
    )


def downgrade() -> None:
    op.drop_table("translations")
