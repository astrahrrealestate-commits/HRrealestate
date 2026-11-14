"""Finance tables (spec 2026-10-31 quote checker, migration 0022): scope, uniques, indexes, nullability."""

from sqlalchemy import Numeric, String, Table, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

import app.db.models  # noqa: F401  (registers tables)
from app.db.base import Base

FINANCE_TABLES = ("vendor_rates", "price_snapshots", "quotes", "quote_lines", "quote_reviews")


def _unique_names(table: Table) -> set[str]:
    return {str(u.name) for u in table.constraints if isinstance(u, UniqueConstraint)}


def _index_columns(table: Table) -> set[tuple[str, ...]]:
    return {tuple(c.name for c in i.columns) for i in table.indexes}


def test_models_declare_company_scope_and_uniques() -> None:
    tables = Base.metadata.tables
    for name in FINANCE_TABLES:
        assert name in tables, name
        assert not tables[name].c.company_id.nullable, name
    assert "uq_price_snapshots_company_id_action_id_item_key" in _unique_names(tables["price_snapshots"])
    assert "uq_quotes_company_id_source_source_id" in _unique_names(tables["quotes"])
    assert "uq_vendor_rates_company_id_person_id_item_key_valid_from" in _unique_names(tables["vendor_rates"])


def test_lookup_indexes_lead_with_company_id() -> None:
    tables = Base.metadata.tables
    assert ("company_id", "case_id") in _index_columns(tables["price_snapshots"])
    assert ("company_id", "case_id") in _index_columns(tables["quotes"])
    assert ("company_id", "person_id", "item_key") in _index_columns(tables["vendor_rates"])


def test_snapshots_always_belong_to_a_decision() -> None:
    snapshots = Base.metadata.tables["price_snapshots"]
    assert not snapshots.c.action_id.nullable
    assert not snapshots.c.case_id.nullable
    assert snapshots.c.rate_card_amount.nullable
    assert snapshots.c.rate_card_id.nullable
    assert isinstance(snapshots.c.sources.type, JSONB)


def test_unlinked_quotes_keep_case_and_person_optional() -> None:
    quotes = Base.metadata.tables["quotes"]
    assert quotes.c.case_id.nullable
    assert quotes.c.person_id.nullable
    assert quotes.c.work_date.nullable
    assert quotes.c.total.nullable
    assert not quotes.c.quote_date.nullable
    currency = quotes.c.currency.type
    assert isinstance(currency, String)
    assert currency.length == 3


def test_reviews_are_append_only_with_a_json_report() -> None:
    reviews = Base.metadata.tables["quote_reviews"]
    assert not any(isinstance(u, UniqueConstraint) for u in reviews.constraints)
    assert isinstance(reviews.c.report.type, JSONB)
    assert not reviews.c.verdict.nullable


def test_money_and_quantity_precision() -> None:
    lines = Base.metadata.tables["quote_lines"]
    quantity, amount = lines.c.quantity.type, lines.c.amount.type
    assert isinstance(quantity, Numeric)
    assert isinstance(amount, Numeric)
    assert (quantity.scale, amount.scale) == (3, 2)
    assert lines.c.unit_price.nullable
    assert lines.c.vat_included.nullable
