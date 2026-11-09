"""people/units/leases: brixx_ref unique per company (partial, non-NULL)

Revision ID: 0037
Revises: 0036
Create Date: 2026-11-03 11:00:00

The BRIXX directory mapper keys people, units and leases on `brixx_ref`; these partial unique indexes make every
mapper upsert "do once". Rows without a BRIXX reference (identity-first contacts) are unaffected.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("people", "units", "leases")


def upgrade() -> None:
    for table in TABLES:
        op.create_index(
            f"uq_{table}_company_id_brixx_ref",
            table,
            ["company_id", "brixx_ref"],
            unique=True,
            postgresql_where=sa.text("brixx_ref IS NOT NULL"),
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_index(f"uq_{table}_company_id_brixx_ref", table_name=table)
