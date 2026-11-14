"""translations: cache both directions (Dutch to English and English to Dutch)

Revision ID: 0042
Revises: 0041
Create Date: 2026-11-12 10:00:00

`target_lang` joins the unique key so the same source text can be cached once per direction, and `text_en`
becomes `text_translated` because it now holds Dutch for English sources. Existing rows are all Dutch to
English, so they are backfilled with target_lang 'en'.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("translations", sa.Column("target_lang", sa.String(length=8), server_default="en", nullable=False))
    op.alter_column("translations", "text_en", new_column_name="text_translated")
    op.drop_constraint(op.f("uq_translations_company_id_source_hash"), "translations", type_="unique")
    op.create_unique_constraint(
        op.f("uq_translations_company_id_source_hash_target_lang"),
        "translations",
        ["company_id", "source_hash", "target_lang"],
    )


def downgrade() -> None:
    op.execute("DELETE FROM translations WHERE target_lang != 'en'")
    op.drop_constraint(op.f("uq_translations_company_id_source_hash_target_lang"), "translations", type_="unique")
    op.create_unique_constraint(
        op.f("uq_translations_company_id_source_hash"), "translations", ["company_id", "source_hash"]
    )
    op.alter_column("translations", "text_translated", new_column_name="text_en")
    op.drop_column("translations", "target_lang")
