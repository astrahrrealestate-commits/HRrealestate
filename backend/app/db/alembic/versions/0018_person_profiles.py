"""person_profiles: T3 entity memory for tenants and contractors

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-23 16:30:00

Creates the `person_profiles` table (spec: 2026-10-23-agent-memory-context-design §6.2, Task C10).
Stores rolling profile summary (≤ 800 chars), language, preferred channel, open/closed cases count,
and contact statistics per person.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "person_profiles"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("language", sa.String(length=16), server_default="nl", nullable=False),
        sa.Column("preferred_channel", sa.String(length=32), server_default="whatsapp", nullable=False),
        sa.Column("summary", sa.String(length=800), server_default="", nullable=False),
        sa.Column("open_cases", sa.Integer(), server_default="0", nullable=False),
        sa.Column("closed_cases", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_contact_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_hours_p50", sa.Float(), nullable=True),
        sa.Column("source_max_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("profile_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_person_profiles_company_id_companies"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["person_id"], ["people.id"], name=op.f("fk_person_profiles_person_id_people"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_person_profiles")),
    )
    op.create_index(op.f("ix_person_profiles_company_id"), TABLE, ["company_id"], unique=False)
    op.create_index(op.f("ix_person_profiles_person_id"), TABLE, ["person_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_person_profiles_person_id"), table_name=TABLE)
    op.drop_index(op.f("ix_person_profiles_company_id"), table_name=TABLE)
    op.drop_table(TABLE)
