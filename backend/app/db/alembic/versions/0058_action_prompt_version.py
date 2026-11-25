"""action prompt version: which proposer prompt wrote an action, for the draft report

Revision ID: 0058
Revises: 0057
Create Date: 2026-11-26 01:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0058"
down_revision: str | None = "0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("actions", sa.Column("prompt_version", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("actions", "prompt_version")
