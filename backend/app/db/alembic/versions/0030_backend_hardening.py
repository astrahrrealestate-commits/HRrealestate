"""backend hardening: case-insensitive Gmail mailboxes, lookup indexes, messages.pipeline_done_at

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-03 09:00:00

- `channel_accounts`: one Gmail mailbox per address whatever its case (lookups were already case-insensitive). Rows
  that differ only in case cannot be merged automatically (each has its own sync state and messages), so the upgrade
  stops with a clear error instead of guessing which account to keep.
- `drive_reorg_items.document_id` and `dd_reviews.unit_id`: indexes for the per-document and per-unit lookups (and
  their foreign keys).
- `messages.pipeline_done_at`: when the pipeline finished a message, for the drift metric pipeline duration p95.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GMAIL_LOWER = "uq_channel_accounts_gmail_address_lower"
REORG_DOCUMENT = "ix_drive_reorg_items_document_id"
DD_UNIT = "ix_dd_reviews_unit_id"

_CASE_DUPLICATES = """
SELECT count(*) FROM (
    SELECT lower(address) FROM channel_accounts WHERE channel = 'gmail' GROUP BY lower(address) HAVING count(*) > 1
) AS dup
"""


def upgrade() -> None:
    duplicates = op.get_bind().execute(sa.text(_CASE_DUPLICATES)).scalar_one()
    if duplicates:
        raise RuntimeError(
            f"{duplicates} Gmail mailbox address(es) in channel_accounts differ only in case; keep one account per "
            "mailbox (move its gmail_sync_state and messages) before running migration 0030"
        )
    op.create_index(
        GMAIL_LOWER,
        "channel_accounts",
        [sa.text("lower(address)")],
        unique=True,
        postgresql_where=sa.text("channel = 'gmail'"),
    )
    op.create_index(REORG_DOCUMENT, "drive_reorg_items", ["document_id"], unique=False)
    op.create_index(DD_UNIT, "dd_reviews", ["unit_id"], unique=False)
    op.add_column("messages", sa.Column("pipeline_done_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "pipeline_done_at")
    op.drop_index(DD_UNIT, table_name="dd_reviews")
    op.drop_index(REORG_DOCUMENT, table_name="drive_reorg_items")
    op.drop_index(GMAIL_LOWER, table_name="channel_accounts")
