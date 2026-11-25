"""chat client msg id: one outbound WhatsApp row per owner-typed message

Revision ID: 0050
Revises: 0049
Create Date: 2026-11-24 15:00:00

The browser's `client_msg_id` (kept in `messages.meta`) is the idempotency key of an owner-typed send
(`chat:{company_id}:{client_msg_id}`). A partial unique index makes it name at most one outbound WhatsApp row per
company, so a replayed `sends` row can never settle a different message.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "uq_messages_chat_client_msg_id"


def upgrade() -> None:
    op.create_index(
        INDEX,
        "messages",
        ["company_id", sa.text("(meta ->> 'client_msg_id')")],
        unique=True,
        postgresql_where=sa.text(
            "channel = 'whatsapp' AND direction = 'outbound' AND (meta ->> 'client_msg_id') IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="messages")
