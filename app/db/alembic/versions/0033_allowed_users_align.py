"""align allowed_users with the model: restrict company deletes, keep one unique index on email

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-06 16:00:00

- 0032 created both a unique constraint and a unique index on `email`; the model keeps the index only.
- 0032 cascaded company deletes into `allowed_users`; every other company-scoped table restricts them.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "allowed_users"
FK = "fk_allowed_users_company_id_companies"


def upgrade() -> None:
    op.execute("ALTER TABLE allowed_users DROP CONSTRAINT IF EXISTS uq_allowed_users_email")
    op.execute(f"ALTER TABLE allowed_users DROP CONSTRAINT IF EXISTS {FK}")
    op.create_foreign_key(FK, TABLE, "companies", ["company_id"], ["id"], ondelete="RESTRICT")


def downgrade() -> None:
    op.drop_constraint(FK, TABLE, type_="foreignkey")
    op.create_foreign_key(FK, TABLE, "companies", ["company_id"], ["id"], ondelete="CASCADE")
    op.create_unique_constraint("uq_allowed_users_email", TABLE, ["email"])
