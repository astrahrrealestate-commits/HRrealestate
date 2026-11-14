"""owner persona: the markdown writing persona the proposer drafts in, and which persona each draft used

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-03 18:30:00

- `owner_personas`: one editable persona (markdown text) per company. The row is created from the bundled mock on
  first use, so existing companies need no data migration.
- `actions.persona_name` / `persona_version`: the persona a tenant- or contractor-facing draft was written in, shown on
  the dashboard draft card. Null for drafts written before this migration and for template drafts.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "owner_personas"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_owner_personas_company_id_companies"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_owner_personas")),
        sa.UniqueConstraint("company_id", name=op.f("uq_owner_personas_company_id")),
    )
    op.add_column("actions", sa.Column("persona_name", sa.String(length=120), nullable=True))
    op.add_column("actions", sa.Column("persona_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("actions", "persona_version")
    op.drop_column("actions", "persona_name")
    op.drop_table(TABLE)
