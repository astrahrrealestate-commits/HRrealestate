"""due diligence lite: reviews, review documents and cached document reads

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-31 15:00:00

Due Diligence Lite tables (spec 2026-10-31) and `owner_feed.kind` gains `dd_report`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FEED_KINDS_BEFORE = (
    "'approval', 'document_review', 'memory_review', 'quote_review', 'alert', 'briefing', 'task', 'agent_note'"
)
_FEED_KINDS_NOW = (
    "'approval', 'document_review', 'memory_review', 'quote_review', 'dd_report', 'alert', 'briefing', 'task', "
    "'agent_note'"
)
_TABLES = ("dd_document_reads", "dd_review_documents", "dd_reviews")  # drop order: children first


def _swap_feed_kind_check(allowed: str) -> None:
    op.drop_constraint(op.f("ck_owner_feed_kind"), "owner_feed", type_="check")
    op.create_check_constraint(op.f("ck_owner_feed_kind"), "owner_feed", f"kind IN ({allowed})")


def _base_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _company_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["company_id"], ["companies.id"], name=op.f(f"fk_{table}_company_id_companies"), ondelete="RESTRICT"
    )


def _enum_check(table: str, column: str, values: Sequence[str]) -> None:
    allowed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint(op.f(f"ck_{table}_{column}"), table, f"{column} IN ({allowed})")


def _create_reviews() -> None:
    op.create_table(
        "dd_reviews",
        *_base_columns(),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("property_kind", sa.String(length=32), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("run_no", sa.Integer(), server_default="1", nullable=False),
        sa.Column("framework_version", sa.String(length=32), nullable=True),
        sa.Column("verdict", sa.String(length=32), nullable=True),
        sa.Column("report", JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        _company_fk("dd_reviews"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], name=op.f("fk_dd_reviews_unit_id_units")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dd_reviews")),
    )
    _enum_check("dd_reviews", "property_kind", ("apartment", "house", "tenanted_investment"))
    _enum_check("dd_reviews", "status", ("pending", "running", "done", "failed"))
    _enum_check("dd_reviews", "verdict", ("clear_to_review", "needs_documents", "red_flags"))
    op.create_index(
        op.f("ix_dd_reviews_company_id_dd_reviews_created_at"), "dd_reviews", ["company_id", "created_at"]
    )


def _create_review_documents() -> None:
    op.create_table(
        "dd_review_documents",
        *_base_columns(),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        _company_fk("dd_review_documents"),
        sa.ForeignKeyConstraint(
            ["review_id"], ["dd_reviews.id"], name=op.f("fk_dd_review_documents_review_id_dd_reviews"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_dd_review_documents_document_id_documents")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dd_review_documents")),
        sa.UniqueConstraint(
            "review_id", "document_id", name=op.f("uq_dd_review_documents_review_id_document_id")
        ),
    )  # fmt: skip
    op.create_index("ix_dd_review_documents_review", "dd_review_documents", ["company_id", "review_id"])


def _create_document_reads() -> None:
    op.create_table(
        "dd_document_reads",
        *_base_columns(),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("reader_version", sa.String(length=32), nullable=False),
        sa.Column("read", JSONB(), nullable=False),
        sa.Column("unverified", sa.Integer(), server_default="0", nullable=False),
        _company_fk("dd_document_reads"),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_dd_document_reads_document_id_documents")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dd_document_reads")),
        sa.UniqueConstraint(
            "company_id", "document_id", "reader_version",
            name=op.f("uq_dd_document_reads_company_id_document_id_reader_version"),
        ),
    )  # fmt: skip


def upgrade() -> None:
    _swap_feed_kind_check(_FEED_KINDS_NOW)
    _create_reviews()
    _create_review_documents()
    _create_document_reads()


def downgrade() -> None:
    for table in _TABLES:
        op.drop_table(table)  # indexes and constraints go with the table
    op.execute("DELETE FROM owner_feed WHERE kind = 'dd_report'")  # the older constraint cannot hold them
    _swap_feed_kind_check(_FEED_KINDS_BEFORE)
