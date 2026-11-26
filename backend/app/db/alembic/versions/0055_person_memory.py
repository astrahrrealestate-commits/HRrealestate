"""person memory: what EstateOS remembers about one person, on their profile

Revision ID: 0055
Revises: 0054
Create Date: 2026-11-25 21:50:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0055"
down_revision: str | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "person_profiles", sa.Column("memory", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column("person_profiles", sa.Column("memory_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("person_profiles", "memory_at")
    op.drop_column("person_profiles", "memory")
