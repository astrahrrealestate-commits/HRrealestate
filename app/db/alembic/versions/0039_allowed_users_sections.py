"""allowed_users.sections: which dashboard sections a profile may open

Revision ID: 0039
Revises: 0038
Create Date: 2026-11-10 16:00:00

`sections` lists the section keys a profile can see; NULL means every section, so existing rows keep the full access
they have today. The roles `owner` and `superadmin` always see everything and manage profiles. A company with no
such row gets its earliest whitelist entry promoted to `superadmin`, so someone can open the Team page and create the
rest (nothing else would ever make the first superadmin).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PROMOTE_FIRST_ADMIN = """
UPDATE allowed_users SET role = 'superadmin' WHERE id IN (
    SELECT DISTINCT ON (a.company_id) a.id FROM allowed_users a
    WHERE a.is_active AND NOT EXISTS (
        SELECT 1 FROM allowed_users b
        WHERE b.company_id = a.company_id AND b.is_active AND b.role IN ('owner', 'superadmin')
    )
    ORDER BY a.company_id, a.created_at, a.id
)
"""


def upgrade() -> None:
    op.add_column("allowed_users", sa.Column("sections", sa.ARRAY(sa.String(length=32)), nullable=True))
    op.execute(PROMOTE_FIRST_ADMIN)


def downgrade() -> None:
    op.drop_column("allowed_users", "sections")
