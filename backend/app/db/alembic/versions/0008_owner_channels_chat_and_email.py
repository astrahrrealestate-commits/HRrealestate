"""Owner settings: chat_user, interactive_channel; Channel gains google_chat

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-09 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHANNEL_TABLES = [
    ("channel_accounts", "channel"),
    ("raw_events", "provider"),
    ("channel_identities", "channel"),
    ("messages", "channel"),
    ("sends", "channel"),
]


def upgrade() -> None:
    op.add_column("owner_accounts", sa.Column("chat_user", sa.String(length=200), nullable=True))
    op.add_column(
        "owner_accounts",
        sa.Column("interactive_channel", sa.String(length=32), server_default="whatsapp", nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_owner_accounts_interactive_channel"),
        "owner_accounts",
        "interactive_channel IN ('whatsapp', 'google_chat')",
    )

    for table, col in _CHANNEL_TABLES:
        op.drop_constraint(op.f(f"ck_{table}_{col}"), table, type_="check")
        op.create_check_constraint(
            op.f(f"ck_{table}_{col}"),
            table,
            f"{col} IN ('whatsapp', 'gmail', 'google_chat')",
        )


def downgrade() -> None:
    for table, col in _CHANNEL_TABLES:
        op.drop_constraint(op.f(f"ck_{table}_{col}"), table, type_="check")
        op.create_check_constraint(
            op.f(f"ck_{table}_{col}"),
            table,
            f"{col} IN ('whatsapp', 'gmail')",
        )

    op.drop_constraint(op.f("ck_owner_accounts_interactive_channel"), "owner_accounts", type_="check")
    op.drop_column("owner_accounts", "interactive_channel")
    op.drop_column("owner_accounts", "chat_user")
