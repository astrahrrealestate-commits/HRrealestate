"""model call messages: which messages a call's prompt carried, so erasure can blank it

Revision ID: 0057
Revises: 0056
Create Date: 2026-11-26 00:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_calls",
        sa.Column("message_ids", postgresql.ARRAY(sa.Uuid()), server_default=sa.text("'{}'::uuid[]"), nullable=False),
    )
    op.create_index("ix_model_calls_message_ids", "model_calls", ["message_ids"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_model_calls_message_ids", table_name="model_calls")
    op.drop_column("model_calls", "message_ids")
