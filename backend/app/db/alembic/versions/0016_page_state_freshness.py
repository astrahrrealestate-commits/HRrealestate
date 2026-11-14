"""Page pre-warm freshness: (company_id, created_at) on messages, approvals and case_events, (company_id, decided_at)
on approvals

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-23 15:00:00

`page_state.latest_change` reads the company's newest message, approval (created or decided) and case event on every
candidate reuse of warmed page facts; each max() is an index-only lookup on these. None of the tables had such an
index (messages has (company_id, thread_ref) and the thread expression index; approvals and case_events only a
single-column company_id index). The new composites lead with company_id, so the single-column company_id indexes of
approvals and case_events become redundant and are dropped (the metadata rule: company_id indexed once as a leading
column). A plain CREATE INDEX briefly blocks writes to these tables; at Phase 1 volume that is a short moment.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW = (
    ("ix_messages_company_id_messages_created_at", "messages", ["company_id", "created_at"]),
    ("ix_approvals_company_id_approvals_created_at", "approvals", ["company_id", "created_at"]),
    ("ix_approvals_company_id_approvals_decided_at", "approvals", ["company_id", "decided_at"]),
    ("ix_case_events_company_id_case_events_created_at", "case_events", ["company_id", "created_at"]),
)
REDUNDANT = (("ix_approvals_company_id", "approvals"), ("ix_case_events_company_id", "case_events"))


def upgrade() -> None:
    for name, table, columns in NEW:
        op.create_index(op.f(name), table, columns, unique=False)
    for name, table in REDUNDANT:
        op.drop_index(op.f(name), table_name=table)


def downgrade() -> None:
    for name, table in REDUNDANT:
        op.create_index(op.f(name), table, ["company_id"], unique=False)
    for name, table, _ in reversed(NEW):
        op.drop_index(op.f(name), table_name=table)
