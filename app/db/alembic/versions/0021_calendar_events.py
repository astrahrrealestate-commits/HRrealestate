"""calendar_events: proposed and confirmed contractor visits and inspections

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-31 12:00:00

Creates the `calendar_events` table behind `app.db.models.calendar.CalendarEventRow` (calendar scheduling agent,
merged in PR #15 without a migration). Column, constraint and index names follow the model and naming convention.
`actions.type` gains `calendar_event` (ActionType grew in the same PR). Downgrade refuses while calendar_event actions
exist (they carry approvals and sends; deleting them would lose audit rows).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "calendar_events"
INDEXES: tuple[tuple[str, list[str]], ...] = (
    ("ix_calendar_events_case_id", ["case_id"]),
    ("ix_calendar_events_unit_id", ["unit_id"]),
    ("ix_calendar_events_start_time", ["start_time"]),
    ("ix_calendar_events_end_time", ["end_time"]),
    ("ix_calendar_events_status", ["status"]),
    ("ix_calendar_events_company_id_calendar_events_status", ["company_id", "status"]),
    ("ix_calendar_events_start_time_calendar_events_end_time", ["start_time", "end_time"]),
)
_ACTION_TYPES_BEFORE = (
    "'reply_draft', 'notify_owner', 'create_reminder', 'update_case_state', 'request_contractor', 'escalate'"
)
_ACTION_TYPES_NOW = f"{_ACTION_TYPES_BEFORE}, 'calendar_event'"


def _swap_action_type_check(allowed: str) -> None:
    op.drop_constraint(op.f("ck_actions_type"), "actions", type_="check")
    op.create_check_constraint(op.f("ck_actions_type"), "actions", f"type IN ({allowed})")


def upgrade() -> None:
    _swap_action_type_check(_ACTION_TYPES_NOW)
    op.create_table(
        TABLE,
        sa.Column("case_id", sa.Uuid(), nullable=True),
        sa.Column("unit_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="proposed", nullable=False),
        sa.Column("event_type", sa.String(length=32), server_default="contractor_repair", nullable=False),
        sa.Column("external_event_id", sa.String(length=128), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("attendees", JSONB(), server_default="[]", nullable=False),
        sa.Column("lockbox_code", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], name=op.f("fk_calendar_events_case_id_cases")),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], name=op.f("fk_calendar_events_unit_id_units")),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_calendar_events_company_id_companies"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calendar_events")),
    )
    for name, columns in INDEXES:
        op.create_index(name, TABLE, columns, unique=False)


def downgrade() -> None:
    _swap_action_type_check(_ACTION_TYPES_BEFORE)
    for name, _columns in reversed(INDEXES):
        op.drop_index(name, table_name=TABLE)
    op.drop_table(TABLE)
