"""understanding research: the web and reference findings behind a draft (M13 T8)

Revision ID: 0060
Revises: 0059
Create Date: 2026-11-26 10:00:00

The `Understanding` contract forbids extra fields, so the findings get their own column: `{"findings": [...],
"unanswered": [...]}`, written once per message. NULL means nobody researched yet.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0060"
down_revision: str | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("understandings", sa.Column("research", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("understandings", "research")
