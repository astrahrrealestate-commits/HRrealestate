"""Measurement metrics on model_calls: tokens_cached and prefix_hash

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-23 16:00:00

Adds `tokens_cached` and `prefix_hash` to `model_calls` so LLM provider prompt cache hits and stable prefix hashes
can be measured per agent (spec: 2026-10-23-agent-memory-context-design §9, Task C1).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "model_calls"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("tokens_cached", sa.Integer(), nullable=True))
    op.add_column(TABLE, sa.Column("prefix_hash", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column(TABLE, "prefix_hash")
    op.drop_column(TABLE, "tokens_cached")
