"""inbox thread state: persist read marker and snooze timestamp on cases

Revision ID: 0053
Revises: 0052
Create Date: 2026-11-25 00:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("cases", sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("cases", "snoozed_until")
    op.drop_column("cases", "last_read_at")
