"""allowed_users: an email is unique within a company, not across all of them

Revision ID: 0040
Revises: 0039
Create Date: 2026-11-11 10:00:00

The table's own key made an address unique across every company, so one company's admin could learn that an address
is whitelisted somewhere (a 409 on create). The key becomes (company_id, lower(email)); `lower(email)` stays indexed
for the Google login, which now refuses an address that is whitelisted in more than one company.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "allowed_users"
OLD = "ix_allowed_users_email"
COMPANY_ONLY = "ix_allowed_users_company_id"
PER_COMPANY = "uq_allowed_users_company_email_lower"
LOGIN_LOOKUP = "ix_allowed_users_email_lower"

_CASE_DUPLICATES = """
SELECT count(*) FROM (
    SELECT 1 FROM allowed_users GROUP BY company_id, lower(email) HAVING count(*) > 1
) AS dup
"""
_CROSS_COMPANY = """
SELECT count(*) FROM (
    SELECT 1 FROM allowed_users GROUP BY email HAVING count(*) > 1
) AS dup
"""


def upgrade() -> None:
    duplicates = op.get_bind().execute(sa.text(_CASE_DUPLICATES)).scalar_one()
    if duplicates:
        raise RuntimeError(
            f"{duplicates} allowed_users email(s) differ only in case within one company; keep one row each "
            "before running migration 0040"
        )
    op.execute(f"DROP INDEX IF EXISTS {OLD}")
    op.execute(f"DROP INDEX IF EXISTS {COMPANY_ONLY}")  # the per-company key below leads with company_id
    op.execute(f"DROP INDEX IF EXISTS {PER_COMPANY}")
    op.execute(f"DROP INDEX IF EXISTS {LOGIN_LOOKUP}")
    op.create_index(PER_COMPANY, TABLE, ["company_id", sa.text("lower(email)")], unique=True)
    op.create_index(LOGIN_LOOKUP, TABLE, [sa.text("lower(email)")], unique=False)


def downgrade() -> None:
    shared = op.get_bind().execute(sa.text(_CROSS_COMPANY)).scalar_one()
    if shared:
        raise RuntimeError(
            f"{shared} allowed_users email(s) are whitelisted in more than one company; remove the extra rows "
            "before downgrading 0040"
        )
    op.drop_index(LOGIN_LOOKUP, table_name=TABLE)
    op.drop_index(PER_COMPANY, table_name=TABLE)
    op.create_index(COMPANY_ONLY, TABLE, ["company_id"], unique=False)
    op.create_index(OLD, TABLE, ["email"], unique=True)
