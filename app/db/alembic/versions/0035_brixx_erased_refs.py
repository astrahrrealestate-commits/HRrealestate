"""brixx_erased_refs: GDPR tombstones for erased BRIXX relaties

Revision ID: 0035
Revises: 0034
Create Date: 2026-11-03 09:00:00

The mirror upsert and the directory mapper skip tombstoned relaties, so a re-sync never resurrects an erased person.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "brixx_erased_refs"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("relatie_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_brixx_erased_refs_company_id_companies"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_brixx_erased_refs")),
        sa.UniqueConstraint("company_id", "relatie_id", name=op.f("uq_brixx_erased_refs_company_id_relatie_id")),
    )


def downgrade() -> None:
    op.drop_table(TABLE)
