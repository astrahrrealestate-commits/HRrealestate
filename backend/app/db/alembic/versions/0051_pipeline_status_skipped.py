"""pipeline status skipped: WhatsApp messages that live only in Chats

Revision ID: 0051
Revises: 0050
Create Date: 2026-11-25 12:00:00

A WhatsApp message from a number the directory does not know is stored for the Chats page but never enters the case
pipeline, search or page memory (ADR 0015). `skipped` marks such a row; the existing `pipeline_status` column and its
CHECK are widened, nothing else changes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK = "ck_messages_pipeline_status"


def upgrade() -> None:
    op.drop_constraint(op.f(CHECK), "messages", type_="check")
    # NOT VALID then VALIDATE: the widened CHECK is enforced for new rows at once, and the full-table scan that proves
    # the old rows runs without blocking webhook inserts and readers.
    op.execute(
        f"ALTER TABLE messages ADD CONSTRAINT {CHECK} "
        "CHECK (pipeline_status IN ('pending', 'done', 'failed', 'skipped')) NOT VALID"
    )
    op.execute(f"ALTER TABLE messages VALIDATE CONSTRAINT {CHECK}")


def downgrade() -> None:
    op.execute("UPDATE messages SET pipeline_status = 'done' WHERE pipeline_status = 'skipped'")
    op.drop_constraint(op.f(CHECK), "messages", type_="check")
    op.create_check_constraint(op.f(CHECK), "messages", "pipeline_status IN ('pending', 'done', 'failed')")
