"""Dashboard channel, owner_feed, agent conversations/turns, companies.outbound_mode

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-15 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHANNEL_TABLES = [
    ("channel_accounts", "channel"),
    ("raw_events", "provider"),
    ("channel_identities", "channel"),
    ("messages", "channel"),
    ("sends", "channel"),
]
_OLD = "('whatsapp', 'gmail', 'google_chat')"
_NEW = "('whatsapp', 'gmail', 'google_chat', 'dashboard')"
_OLD_INTERACTIVE = "interactive_channel IN ('whatsapp', 'google_chat')"
_NEW_INTERACTIVE = "interactive_channel IN ('whatsapp', 'google_chat', 'dashboard')"


def _swap_channel_checks(values: str) -> None:
    for table, col in _CHANNEL_TABLES:
        op.drop_constraint(op.f(f"ck_{table}_{col}"), table, type_="check")
        op.create_check_constraint(op.f(f"ck_{table}_{col}"), table, f"{col} IN {values}")


def _swap_interactive_check(expr: str) -> None:
    name = op.f("ck_owner_accounts_interactive_channel")
    op.drop_constraint(name, "owner_accounts", type_="check")
    op.create_check_constraint(name, "owner_accounts", expr)


def _create_owner_feed() -> None:
    op.create_table(
        "owner_feed",
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("ref_id", sa.Uuid(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_owner_feed_company_id_companies"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_owner_feed")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_owner_feed_idempotency_key")),
    )
    op.create_index(
        op.f("ix_owner_feed_company_id_owner_feed_created_at_owner_feed_id"),
        "owner_feed",
        ["company_id", "created_at", "id"],
        unique=False,
    )
    op.create_check_constraint(
        op.f("ck_owner_feed_kind"),
        "owner_feed",
        "kind IN ('approval', 'document_review', 'alert', 'briefing', 'task', 'agent_note')",
    )


def _create_agent_tables() -> None:
    op.create_table(
        "agent_conversations",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_agent_conversations_company_id_companies"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["owner_accounts.id"], name=op.f("fk_agent_conversations_owner_id_owner_accounts")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_conversations")),
    )
    op.create_index(
        op.f("ix_agent_conversations_company_id"), "agent_conversations", ["company_id"], unique=False
    )
    op.create_table(
        "agent_turns",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("plan", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("prompt_ref", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_agent_turns_company_id_companies"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["agent_conversations.id"],
            name=op.f("fk_agent_turns_conversation_id_agent_conversations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_turns")),
    )
    op.create_index(
        op.f("ix_agent_turns_company_id_agent_turns_conversation_id_agent_turns_created_at"),
        "agent_turns",
        ["company_id", "conversation_id", "created_at"],
        unique=False,
    )
    op.create_check_constraint(
        op.f("ck_agent_turns_status"), "agent_turns", "status IN ('pending', 'running', 'done', 'failed')"
    )


def upgrade() -> None:
    _swap_channel_checks(_NEW)
    _swap_interactive_check(_NEW_INTERACTIVE)
    op.add_column(
        "companies", sa.Column("outbound_mode", sa.String(length=32), server_default="draft", nullable=False)
    )
    op.create_check_constraint(
        op.f("ck_companies_outbound_mode"), "companies", "outbound_mode IN ('draft', 'send')"
    )
    _create_owner_feed()
    _create_agent_tables()


def downgrade() -> None:
    op.drop_table("agent_turns")
    op.drop_table("agent_conversations")
    op.drop_table("owner_feed")
    op.drop_constraint(op.f("ck_companies_outbound_mode"), "companies", type_="check")
    op.drop_column("companies", "outbound_mode")
    _swap_interactive_check(_OLD_INTERACTIVE)
    _swap_channel_checks(_OLD)
