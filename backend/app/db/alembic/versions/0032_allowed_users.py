"""whitelist of authorized users permitted to log in to EstateOS

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-06 14:00:00

- `allowed_users`: whitelist table restricting platform login to verified emails.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "allowed_users"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=50), server_default="manager", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("invited_by", sa.String(length=320), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_allowed_users_company_id_companies"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_allowed_users")),
        sa.UniqueConstraint("email", name=op.f("uq_allowed_users_email")),
    )
    op.create_index(op.f("ix_allowed_users_company_id"), TABLE, ["company_id"], unique=False)
    op.create_index(op.f("ix_allowed_users_email"), TABLE, ["email"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_allowed_users_email"), table_name=TABLE)
    op.drop_index(op.f("ix_allowed_users_company_id"), table_name=TABLE)
    op.drop_table(TABLE)
