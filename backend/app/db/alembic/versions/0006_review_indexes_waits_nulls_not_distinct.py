"""review indexes; one open wait per case even without a party

Indexes found missing in review: waits.source_action_id (FK), documents.model_call_id (FK) and
messages(pipeline_status, pipeline_attempts) for the hourly pipeline requeue sweep. uq_waits_open becomes
NULLS NOT DISTINCT (PostgreSQL 15+), so two open waits on the same case with party_person_id NULL also conflict.
Creating it fails if such duplicates already exist; Phase 1 has no production waits yet.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OPEN = sa.text("status = 'waiting'")


def upgrade() -> None:
    op.create_index(op.f('ix_waits_source_action_id'), 'waits', ['source_action_id'], unique=False)
    op.create_index(op.f('ix_documents_model_call_id'), 'documents', ['model_call_id'], unique=False)
    op.create_index(
        op.f('ix_messages_pipeline_status_messages_pipeline_attempts'),
        'messages',
        ['pipeline_status', 'pipeline_attempts'],
        unique=False,
    )
    op.drop_index('uq_waits_open', table_name='waits', postgresql_where=_OPEN)
    op.create_index(
        'uq_waits_open',
        'waits',
        ['case_id', 'party_person_id'],
        unique=True,
        postgresql_where=_OPEN,
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_index('uq_waits_open', table_name='waits', postgresql_where=_OPEN)
    op.create_index('uq_waits_open', 'waits', ['case_id', 'party_person_id'], unique=True, postgresql_where=_OPEN)
    op.drop_index(op.f('ix_messages_pipeline_status_messages_pipeline_attempts'), table_name='messages')
    op.drop_index(op.f('ix_documents_model_call_id'), table_name='documents')
    op.drop_index(op.f('ix_waits_source_action_id'), table_name='waits')
