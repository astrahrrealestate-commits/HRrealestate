"""calendar_events: scheduled visits, inspections, and contractor appointments

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-31 16:00:00

Creates the `calendar_events` table for appointments and property visits.
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


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_calendar_events_company_id_companies"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_calendar_events_case_id_cases"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"], ["units.id"], name=op.f("fk_calendar_events_unit_id_units"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calendar_events")),
    )
    op.create_index(op.f("ix_calendar_events_company_id_status"), TABLE, ["company_id", "status"])
    op.create_index(op.f("ix_calendar_events_start_time_end_time"), TABLE, ["start_time", "end_time"])
    op.create_index(op.f("ix_calendar_events_case_id"), TABLE, ["case_id"])
    op.create_index(op.f("ix_calendar_events_unit_id"), TABLE, ["unit_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_calendar_events_unit_id"), table_name=TABLE)
    op.drop_index(op.f("ix_calendar_events_case_id"), table_name=TABLE)
    op.drop_index(op.f("ix_calendar_events_start_time_end_time"), table_name=TABLE)
    op.drop_index(op.f("ix_calendar_events_company_id_status"), table_name=TABLE)
    op.drop_table(TABLE)

