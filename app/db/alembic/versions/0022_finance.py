"""finance: vendor rates, price snapshots, quotes, quote lines and quote reviews

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-31 12:00:00

Quote checker tables (spec 2026-10-31, M11) and `owner_feed.kind` gains `quote_review`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FEED_KINDS_BEFORE = "'approval', 'document_review', 'memory_review', 'alert', 'briefing', 'task', 'agent_note'"
_FEED_KINDS_NOW = (
    "'approval', 'document_review', 'memory_review', 'quote_review', 'alert', 'briefing', 'task', 'agent_note'"
)
_TABLES = ("quote_reviews", "quote_lines", "quotes", "price_snapshots", "vendor_rates")  # drop order: children first


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


def _fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [f"{target}.id"], name=op.f(f"fk_{table}_{column}_{target}"))


def _enum_check(table: str, column: str, values: Sequence[str]) -> None:
    """The CHECK a `str_enum` column gets from its model."""
    allowed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint(op.f(f"ck_{table}_{column}"), table, f"{column} IN ({allowed})")


def _create_vendor_rates() -> None:
    op.create_table(
        "vendor_rates",
        *_base_columns(),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("item_key", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.String(length=200), nullable=True),
        _company_fk("vendor_rates"),
        _fk("vendor_rates", "person_id", "people"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vendor_rates")),
        sa.UniqueConstraint(
            "company_id", "person_id", "item_key", "valid_from",
            name=op.f("uq_vendor_rates_company_id_person_id_item_key_valid_from"),
        ),
    )  # fmt: skip
    _enum_check("vendor_rates", "source", ("owner", "document", "quote"))
    op.create_index("ix_vendor_rates_lookup", "vendor_rates", ["company_id", "person_id", "item_key"])


def _create_price_snapshots() -> None:
    op.create_table(
        "price_snapshots",
        *_base_columns(),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("action_id", sa.Uuid(), nullable=False),
        sa.Column("item_key", sa.String(length=100), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("low", sa.Numeric(12, 2), nullable=False),
        sa.Column("avg", sa.Numeric(12, 2), nullable=False),
        sa.Column("high", sa.Numeric(12, 2), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("basis", sa.String(length=32), nullable=False),
        sa.Column("sources", JSONB(), server_default="[]", nullable=False),
        sa.Column("rate_card_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("rate_card_id", sa.Uuid(), nullable=True),
        _company_fk("price_snapshots"),
        _fk("price_snapshots", "case_id", "cases"),
        _fk("price_snapshots", "action_id", "actions"),
        _fk("price_snapshots", "rate_card_id", "vendor_rates"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_snapshots")),
        sa.UniqueConstraint(
            "company_id", "action_id", "item_key", name=op.f("uq_price_snapshots_company_id_action_id_item_key")
        ),
    )
    _enum_check("price_snapshots", "basis", ("web", "competitor", "owner", "fake"))
    op.create_index("ix_price_snapshots_company_case", "price_snapshots", ["company_id", "case_id"])


def _create_quotes() -> None:
    op.create_table(
        "quotes",
        *_base_columns(),
        sa.Column("case_id", sa.Uuid(), nullable=True),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("quote_date", sa.Date(), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="received", nullable=False),
        _company_fk("quotes"),
        _fk("quotes", "case_id", "cases"),
        _fk("quotes", "person_id", "people"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quotes")),
        sa.UniqueConstraint("company_id", "source", "source_id", name=op.f("uq_quotes_company_id_source_source_id")),
    )
    _enum_check("quotes", "source", ("message", "document"))
    _enum_check("quotes", "status", ("received", "reviewed", "unlinked"))
    op.create_index("ix_quotes_company_case", "quotes", ["company_id", "case_id"])


def _create_quote_lines() -> None:
    op.create_table(
        "quote_lines",
        *_base_columns(),
        sa.Column("quote_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("item_key", sa.String(length=100), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("vat_included", sa.Boolean(), nullable=True),
        _company_fk("quote_lines"),
        _fk("quote_lines", "quote_id", "quotes"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quote_lines")),
    )
    op.create_index(op.f("ix_quote_lines_company_id"), "quote_lines", ["company_id"])
    op.create_index(op.f("ix_quote_lines_quote_id"), "quote_lines", ["quote_id"])


def _create_quote_reviews() -> None:
    op.create_table(
        "quote_reviews",
        *_base_columns(),
        sa.Column("quote_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_basis", sa.String(length=32), nullable=False),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("overcharge", sa.Numeric(12, 2), nullable=False),
        sa.Column("late_days", sa.Integer(), nullable=False),
        sa.Column("report", JSONB(), nullable=False),
        _company_fk("quote_reviews"),
        _fk("quote_reviews", "quote_id", "quotes"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quote_reviews")),
    )
    _enum_check("quote_reviews", "snapshot_basis", ("decision_day", "estimate_current_prices"))
    _enum_check("quote_reviews", "verdict", ("ok", "needs_check", "above_market", "well_above_market", "above_agreed"))
    op.create_index(op.f("ix_quote_reviews_company_id"), "quote_reviews", ["company_id"])
    op.create_index(op.f("ix_quote_reviews_quote_id"), "quote_reviews", ["quote_id"])


def upgrade() -> None:
    _swap_feed_kind_check(_FEED_KINDS_NOW)
    _create_vendor_rates()
    _create_price_snapshots()
    _create_quotes()
    _create_quote_lines()
    _create_quote_reviews()


def downgrade() -> None:
    for table in _TABLES:
        op.drop_table(table)  # indexes and constraints go with the table
    op.execute("DELETE FROM owner_feed WHERE kind = 'quote_review'")  # the older constraint cannot hold them
    _swap_feed_kind_check(_FEED_KINDS_BEFORE)
