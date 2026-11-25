"""reference documents: company papers (ROZ provisions, standard terms) every dossier may read

Revision ID: 0056
Revises: 0055
Create Date: 2026-11-25 22:05:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0056"
down_revision: str | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("is_reference", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    op.drop_column("documents", "is_reference")
