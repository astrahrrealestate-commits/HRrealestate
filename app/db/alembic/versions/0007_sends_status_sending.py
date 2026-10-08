"""sends.status gains 'sending': one attempt claims a send atomically, a second attempt never re-sends blind

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-08 12:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_sends_status"), "sends", type_="check")
    op.create_check_constraint(
        op.f("ck_sends_status"), "sends", "status IN ('pending', 'sending', 'sent', 'failed')"
    )


def downgrade() -> None:
    op.execute("UPDATE sends SET status = 'failed' WHERE status = 'sending'")
    op.drop_constraint(op.f("ck_sends_status"), "sends", type_="check")
    op.create_check_constraint(op.f("ck_sends_status"), "sends", "status IN ('pending', 'sent', 'failed')")
