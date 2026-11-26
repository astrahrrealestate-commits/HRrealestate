"""pipeline status held: reloaded history mail stored but not yet released to the pipeline

Revision ID: 0059
Revises: 0058
Create Date: 2026-11-25 22:30:00

M13 reloads a mailbox in history mode: each mail is stored first and released later, oldest first. `held` marks a stored
one that nothing may pick up yet. The existing `pipeline_status` CHECK is widened, nothing else changes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0059"
down_revision: str | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK = "ck_messages_pipeline_status"
OLD = "('pending', 'done', 'failed', 'skipped')"
NEW = "('pending', 'done', 'failed', 'held', 'skipped')"


def _widen(values: str) -> None:
    op.drop_constraint(op.f(CHECK), "messages", type_="check")
    # NOT VALID then VALIDATE: the full-table scan runs without blocking inserts and readers (as 0051).
    op.execute(f"ALTER TABLE messages ADD CONSTRAINT {CHECK} CHECK (pipeline_status IN {values}) NOT VALID")
    op.execute(f"ALTER TABLE messages VALIDATE CONSTRAINT {CHECK}")


def upgrade() -> None:
    _widen(NEW)


def downgrade() -> None:
    op.execute("UPDATE messages SET pipeline_status = 'done' WHERE pipeline_status = 'held'")
    _widen(OLD)
